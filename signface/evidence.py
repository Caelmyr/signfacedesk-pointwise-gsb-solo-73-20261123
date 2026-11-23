import csv
import hashlib
import io
import json
import zipfile

from image_lab.validation import Invalid


def report_csv(reading):
    rows = reading["rows"]
    fields = list(dict.fromkeys(key for row in rows for key in row))
    output = io.StringIO(newline="")
    if not fields:
        return "measurement\r\n"
    writer = csv.DictWriter(output, fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def manifest(library, reading):
    cover = {"schema": "signface_survey_1", "reading": reading, "members": {}}
    files = {
        "inspection.png": library.object(reading["image"]).read_bytes(),
        "readings.csv": report_csv(reading).encode(),
    }
    for entry in reading["captures"]:
        files["capture-" + entry["id"] + ".bin"] = library.object(entry["digest"]).read_bytes()
    total = sum(map(len, files.values()))
    if total > 40 * 1024 * 1024:
        raise Invalid("The photographs exceed the inspection packet limit.")
    cover["members"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    packet = io.BytesIO()
    with zipfile.ZipFile(packet, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in files.items():
            zf.writestr(name, raw)
        zf.writestr("inspection.json", json.dumps(cover, indent=2))
    return packet.getvalue()


def verify(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as packet:
            members = packet.infolist()
            if len(members) < 3 or len(members) > 10 or sum(item.file_size for item in members) > 48 * 1024 * 1024:
                raise Invalid("The ZIP is not a supported inspection packet.")
            names = [item.filename for item in members]
            if len(set(names)) != len(names) or "inspection.json" not in names:
                raise Invalid("The packet manifest or member list is invalid.")
            if packet.getinfo("inspection.json").file_size > 1024 * 1024:
                raise Invalid("The packet manifest is too large.")
            cover = json.loads(packet.read("inspection.json"))
            if not isinstance(cover, dict) or cover.get("schema") != "signface_survey_1":
                raise Invalid("This ZIP has no SignFace Desk inspection manifest.")
            expected = cover.get("members")
            if not isinstance(expected, dict) or set(expected) != set(names) - {"inspection.json"}:
                raise Invalid("The manifest does not match the complete ZIP contents.")
            verified = []
            for name, digest in expected.items():
                if hashlib.sha256(packet.read(name)).hexdigest() != digest:
                    raise Invalid(f"The stored digest differs for {name}.")
                verified.append(name)
            reading = cover.get("reading")
            if not isinstance(reading, dict) or reading.get("image") != expected.get("inspection.png"):
                raise Invalid("The inspection image does not match the unchanged record.")
            captures = reading.get("captures")
            if not isinstance(captures, list) or not captures:
                raise Invalid("The inspection has no recorded source captures.")
            for capture in captures:
                if not isinstance(capture, dict) or "id" not in capture or "digest" not in capture:
                    raise Invalid("A source capture has no complete record.")
                if expected.get("capture-" + str(capture["id"]) + ".bin") != capture["digest"]:
                    raise Invalid("A source capture does not match the recorded digest.")
            return {"verified": sorted(verified), "title": str(reading.get("title", "")), "mode": str(reading.get("mode", ""))}
    except (zipfile.BadZipFile, json.JSONDecodeError, RuntimeError, UnicodeError, NotImplementedError) as exc:
        raise Invalid("The ZIP could not be read as an inspection packet.") from exc
