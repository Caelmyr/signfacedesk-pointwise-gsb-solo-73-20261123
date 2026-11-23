import io
from flask import Blueprint, Response, jsonify, render_template, request, send_file
from image_lab.validation import Conflict, Invalid

from . import analysis, demo, evidence
from .model import MARKS, ROLES, TOOLS, choice, locate, mark_fields, number, opts, part_fields
from .photos import basename, canvas, decode, photograph, preview, raw_preview, registered_corners
from .store import Library, key, now


def input_body():
    return opts(request.get_json(silent=True))


def upload(limit):
    file = request.files.get("file")
    if file is None:
        raise Invalid("Choose a file.")
    raw = file.stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise Invalid("The file is empty or exceeds the size limit.")
    return basename(file.filename), raw


def png(blob):
    return Response(blob, mimetype="image/png")


def capture_frame(library, part, capture):
    return photograph(decode(library.object(capture["digest"]).read_bytes()), part, capture["corners"])


def selected_mark(part, mark_id=None, purpose=None, required=False):
    if not mark_id and not required:
        return None
    mark = locate(part["marks"], mark_id, "The marked geometry")
    if purpose and mark["purpose"] != purpose:
        raise Invalid("Choose a mark with the corresponding purpose.")
    return mark


def job_inputs(library, part, data):
    mode = choice(data.get("mode"), TOOLS, "measurement")
    a = locate(part["captures"], data.get("capture"), "The active photograph")
    captures = [a]
    if mode == "coverage":
        b = locate(part["captures"], data.get("other"), "The comparison photograph")
        if a["id"] == b["id"]:
            raise Invalid("Choose a separate comparison photograph.")
        captures.append(b)
    if any(capture["corners"] is None for capture in captures):
        raise Invalid("Register all source photographs before measuring in millimetres.")
    # Region and exclusion geometry are part of the reading's saved inputs.
    frame = capture_frame(library, part, a)
    region = selected_mark(part, data.get("region"), "inspect")
    excludes = [item for item in part["marks"] if item["purpose"] == "ignore"]
    domain = analysis.domain_for(frame, region, excludes)
    mark_inputs = {"region": region, "exclusions": excludes}
    settings = data.get("options", {})
    opts(settings)
    other = capture_frame(library, part, captures[1]) if len(captures) == 2 else None
    return mode, captures, frame, other, domain, mark_inputs, settings


def perform(library, part, data):
    if choice(data.get("mode"), TOOLS, "measurement") == "edge":
        return perform_edge(library, part, data)
    mode, captures, frame, other, domain, marks, settings = job_inputs(library, part, data)
    saved_options = settings
    if mode in ("return", "weak", "contrast"):
        first_purpose, second_purpose = ("letter", "background") if mode == "contrast" else ("reference", "dark")
        first = selected_mark(part, settings.get(first_purpose), first_purpose, True)
        second = selected_mark(part, settings.get(second_purpose), second_purpose, True)
        marks.update({first_purpose: first, second_purpose: second})
        measure = {"return": analysis.relative_return, "weak": analysis.weak_patches, "contrast": analysis.contrast}[mode]
        summary, rows, out = measure(frame, domain, settings, first, second)
    elif mode == "glyph":
        first = selected_mark(part, settings.get("letter"), "letter", True)
        second = selected_mark(part, settings.get("background"), "background", True)
        marks.update({"letter": first, "background": second})
        summary, rows, out, adopted = analysis.glyph(frame, domain, settings, first, second)
        marks["adopted"] = {"name": "Adopted glyph outline (candidate " + summary["adopted_candidate"] + ")",
                            "purpose": "adopted", "points": adopted}
        # Only the adopted outline stays in the report; rejected candidate geometry is not kept.
        saved_options = {name: value for name, value in settings.items() if not name.startswith("candidate_")}
    elif mode == "coverage":
        summary, rows, out = analysis.coverage(frame, other, domain, settings)
    else:
        measure = {"outline": analysis.outline, "holes": analysis.holes, "profile": analysis.profile,
                   "surface": analysis.surface, "glare": analysis.glare, "scuffs": analysis.scuffs}[mode]
        summary, rows, out = measure(frame, domain, settings)
    return {"mode": mode, "title": TOOLS[mode][0], "source_part": part["name"], "lot": part["lot"],
            "plane_mm": [part["width_mm"], part["height_mm"]], "summary": summary, "rows": rows,
            "image": library.put(preview(out)), "marks": marks, "captures": captures, "options": saved_options}


def perform_edge(library, part, data):
    """Frame a character edge on the photograph and outline stored in a glyph report."""
    settings = opts(data.get("options", {}))
    source = library.reading(settings.get("glyph", ""))
    if source.get("part") != part["id"] or source.get("mode") != "glyph":
        raise Invalid("Choose a glyph outline report saved for this sign.")
    adopted = (source.get("marks") or {}).get("adopted")
    if not isinstance(adopted, dict) or not adopted.get("points"):
        raise Invalid("The chosen report does not hold an adopted glyph outline.")
    capture = source["captures"][0]
    if capture.get("corners") is None:
        raise Invalid("The glyph report's photograph is no longer registered.")
    if not data.get("region"):
        raise Invalid("Frame the character edge with an inspection region mark.")
    region = selected_mark(part, data.get("region"), "inspect", True)
    excludes = [item for item in part["marks"] if item["purpose"] == "ignore"]
    frame = capture_frame(library, part, capture)
    domain = analysis.domain_for(frame, region, excludes)
    summary, rows, out = analysis.edge(frame, domain, settings, adopted["points"])
    marks = {"region": region, "exclusions": excludes, "adopted": adopted}
    return {"mode": "edge", "title": TOOLS["edge"][0], "source_part": part["name"], "lot": part["lot"],
            "plane_mm": [part["width_mm"], part["height_mm"]], "summary": summary, "rows": rows,
            "image": library.put(preview(out)), "marks": marks, "captures": [capture], "options": settings}


def install(app, root):
    library = Library(root)
    api = Blueprint("signface", __name__, url_prefix="/survey")

    @app.get("/")
    def desk():
        return render_template("signface.html")

    @api.get("/health")
    def health():
        return jsonify(status="ok", application="SignFace Desk")

    @api.get("/config")
    def config():
        return jsonify(roles=ROLES, marks=MARKS, tools=TOOLS)

    @api.get("/parts")
    def list_parts():
        return jsonify(items=library.parts())

    @api.post("/parts")
    def new_part():
        return jsonify(library.create(part_fields(input_body()))), 201

    @api.post("/training")
    def new_demo():
        return jsonify(demo.training(library)), 201

    @api.get("/parts/<part_id>")
    def get_part(part_id):
        return jsonify(library.part(part_id))

    @api.post("/parts/<part_id>/captures")
    def add_capture(part_id):
        name, raw = upload(18 * 1024 * 1024)
        role = choice(request.form.get("role"), ROLES, "photograph role")
        version = int(number(request.form.get("revision"), "revision", 1, 10**9))
        decode(raw)
        def apply(doc):
            if len(doc["captures"]) >= 12:
                raise Invalid("A sign can hold up to twelve photographs.")
            doc["captures"].append({"id": key(), "role": role, "name": name, "digest": library.put(raw), "corners": None,
                                    "created_at": now(), "synthetic": False})
        return jsonify(library.update(part_id, version, apply)), 201

    @api.put("/parts/<part_id>/captures/<capture_id>/registration")
    def register(part_id, capture_id):
        data = input_body()
        corners = registered_corners(data.get("corners"))
        def apply(doc):
            cap = locate(doc["captures"], capture_id, "The photograph")
            cap["corners"] = corners
        return jsonify(library.update(part_id, data.get("revision"), apply))

    @api.get("/parts/<part_id>/captures/<capture_id>/image")
    def capture_image(part_id, capture_id):
        part = library.part(part_id)
        capture = locate(part["captures"], capture_id, "The photograph")
        raw = decode(library.object(capture["digest"]).read_bytes())
        if request.args.get("view") == "raw":
            return png(raw_preview(raw))
        frame = photograph(raw, part, capture["corners"])
        return png(preview(canvas(frame), part["marks"] if request.args.get("view") == "marks" else []))

    @api.get("/parts/<part_id>/captures/<capture_id>/source")
    def original(part_id, capture_id):
        part = library.part(part_id)
        capture = locate(part["captures"], capture_id, "The photograph")
        return send_file(library.object(capture["digest"]), as_attachment=True, download_name=capture["name"], mimetype="application/octet-stream")

    @api.post("/parts/<part_id>/marks")
    def add_mark(part_id):
        data = input_body()
        mark = mark_fields(data)
        def apply(doc):
            if len(doc["marks"]) >= 36:
                raise Invalid("A sign can hold up to thirty-six marks.")
            doc["marks"].append({**mark, "id": key()})
        return jsonify(library.update(part_id, data.get("revision"), apply)), 201

    @api.delete("/parts/<part_id>/marks/<mark_id>")
    def delete_mark(part_id, mark_id):
        data = input_body()
        def apply(doc):
            item = locate(doc["marks"], mark_id, "The mark")
            doc["marks"].remove(item)
        return jsonify(library.update(part_id, data.get("revision"), apply))

    @api.get("/parts/<part_id>/readings")
    def recordings(part_id):
        library.part(part_id)
        return jsonify(items=library.readings(part_id))

    @api.post("/parts/<part_id>/readings")
    def run_reading(part_id):
        data = input_body()
        part = library.part(part_id)
        if data.get("revision") != part["revision"]:
            raise Conflict("The sign changed. Refresh before measuring.")
        return jsonify(library.save(part, perform(library, part, data))), 201

    @api.get("/readings/<reading_id>")
    def get_reading(reading_id):
        return jsonify(library.reading(reading_id))

    @api.get("/readings/<reading_id>/image")
    def reading_image(reading_id):
        return send_file(library.object(library.reading(reading_id)["image"]), mimetype="image/png", max_age=0)

    @api.get("/readings/<reading_id>/csv")
    def reading_csv(reading_id):
        data = evidence.report_csv(library.reading(reading_id)).encode()
        return send_file(io.BytesIO(data), mimetype="text/csv", download_name="inspection.csv", as_attachment=True)

    @api.get("/readings/<reading_id>/packet")
    def reading_packet(reading_id):
        packet = evidence.manifest(library, library.reading(reading_id))
        return send_file(io.BytesIO(packet), mimetype="application/zip", download_name=f"sign-{reading_id}.zip", as_attachment=True)

    @api.post("/verify")
    def verification():
        _, raw = upload(44 * 1024 * 1024)
        return jsonify(evidence.verify(raw))

    app.register_blueprint(api)
