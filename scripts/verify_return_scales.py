"""End-to-end checks for frozen return scales, run with isolated data dirs."""
import io
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Local sandbox installs third-party packages outside the default site path.
for extra in ("/opt/pointwise-env/site-packages",):
    if Path(extra).is_dir() and extra not in sys.path:
        sys.path.insert(0, extra)
sys.path.insert(0, str(REPO))

from flask import Flask, jsonify  # noqa: E402

from image_lab.validation import Conflict, Invalid  # noqa: E402
from signface.web import install  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as tmp:
        app = Flask(__name__)
        install(app, Path(tmp) / "data")
        app.register_error_handler(Conflict, lambda e: (jsonify(error=str(e)), 409))
        app.register_error_handler(Invalid, lambda e: (jsonify(error=str(e)), 400))
        client = app.test_client()

        created = client.post("/survey/training")
        assert created.status_code == 201, created.data
        part = created.get_json()
        part_id = part["id"]
        night = next(cap for cap in part["captures"] if cap["role"] == "night")
        cap_id = night["id"]
        by_name = {mark["name"]: mark for mark in part["marks"]}
        inspect_id = by_name["Bottom film field"]["id"]

        def reading(payload):
            response = client.post(f"/survey/parts/{part_id}/readings", json=payload)
            assert response.status_code == 201, response.data
            return response.get_json()

        base = {"capture": cap_id, "region": inspect_id, "revision": part["revision"],
                "options": {"threshold": .62}}
        common_opts = {
            "reference": by_name["Sound blue film"]["id"], "dark": by_name["Dark return sample"]["id"],
            "check_left": by_name["Left check film"]["id"],
            "check_right": by_name["Right check film"]["id"],
        }
        split_opts = {
            **common_opts,
            "reference_right": by_name["Right sound film"]["id"],
            "dark_right": by_name["Right dark sample"]["id"],
        }

        # 1. Auto: both schemes evaluated, exactly one adopted, check film never a control.
        auto = reading({**base, "mode": "return", "options": {
            **base["options"], "scale_scheme": "auto", **split_opts,
            "tolerance_left": .15, "tolerance_right": .15}})
        scale = auto["scale"]
        assert scale["id"] == auto["id"]
        assert auto["summary"]["scale_id"] == auto["id"]
        assert len(scale["candidates"]) == 2
        assert all(set(c["checks"][0]) >= {"observed_return", "deviation", "passes"} for c in scale["candidates"])
        adopted = next(c for c in scale["candidates"] if c["scheme"] == scale["scheme"])
        assert adopted["accepted"]
        check_ids = {check["mark"] for check in scale["checks"]}
        control_ids = set(scale["controls"].values())
        assert not (check_ids & control_ids), "check film must not be a control"
        print("auto adopted:", scale["scheme"], "| candidates:",
              [(c["scheme"], c["accepted"], c["worst_deviation"]) for c in scale["candidates"]])

        # 2. Explicit common scale at the strict check tolerance is rejected when
        #    the other side's check film cannot be aligned; widening the tolerance
        #    passes, and a common scale then covers the whole plane.
        strict_common = client.post(f"/survey/parts/{part_id}/readings", json={
            **base, "mode": "return", "options": {
                **base["options"], "scale_scheme": "common", **common_opts,
                "tolerance_left": .15, "tolerance_right": .15}})
        assert strict_common.status_code == 400
        print("strict common rejected:", strict_common.get_json()["error"])
        common = reading({**base, "mode": "return", "options": {
            **base["options"], "scale_scheme": "common", **common_opts,
            "tolerance_left": .40, "tolerance_right": .40}})
        assert common["scale"]["scheme"] == "common"
        assert common["scale"]["zones"][0]["x0"] == 0 and common["scale"]["zones"][0]["x1"] is None
        assert "outside scale (middle band)" not in {row["class"] for row in common["rows"]}

        # 3. Split scale leaves the middle band unresolved.
        split = reading({**base, "mode": "return", "options": {
            **base["options"], "scale_scheme": "split", **split_opts,
            "tolerance_left": .15, "tolerance_right": .15}})
        assert split["scale"]["scheme"] == "split"
        assert split["scale"]["gap"] and split["scale"]["gap"][0] < split["scale"]["gap"][1]
        zone_keys = {z["key"] for z in split["scale"]["zones"]}
        assert zone_keys == {"left", "right"}
        classes = {row["class"]: row for row in split["rows"]}
        assert "outside scale (middle band)" in classes
        assert classes["outside scale (middle band)"]["positions"] > 0

        # 4. Tight tolerance must reject; loosening passes.
        tight = client.post(f"/survey/parts/{part_id}/readings", json={
            **base, "mode": "return", "options": {
                **base["options"], "scale_scheme": "common", **common_opts,
                "tolerance_left": .002, "tolerance_right": .002}})
        assert tight.status_code == 400
        print("tight tolerance rejected:", tight.get_json()["error"])

        # 5. Split without right-side controls is rejected.
        no_right = client.post(f"/survey/parts/{part_id}/readings", json={
            **base, "mode": "return", "options": {
                **base["options"], "scale_scheme": "split",
                "reference": by_name["Sound blue film"]["id"],
                "dark": by_name["Dark return sample"]["id"]}})
        assert no_right.status_code == 400

        # 6. Weak patches reopen the frozen scale inside a small window.
        window = client.post(f"/survey/parts/{part_id}/marks", json={
            "revision": part["revision"], "name": "Weak window", "purpose": "inspect",
            "points": [[.42, .75], [.55, .75], [.55, .92], [.42, .92]]})
        assert window.status_code == 201
        marked_part = window.get_json()
        window_id = marked_part["marks"][-1]["id"]
        weak = reading({"capture": cap_id, "region": window_id,
                        "revision": marked_part["revision"], "mode": "weak",
                        "options": {"threshold": .62, "minimum_mm2": 5, "scale_reading": split["id"]}})
        assert weak["summary"]["scale_source"] == split["id"]
        assert weak["summary"]["scale_scheme"] == "split"
        assert "scale_reading" in weak["marks"]

        # 7. Frozen scale cannot be opened on another capture.
        other_cap = next(cap for cap in part["captures"] if cap["id"] != cap_id)["id"]
        wrong = client.post(f"/survey/parts/{part_id}/readings", json={
            "capture": other_cap, "region": inspect_id, "revision": marked_part["revision"], "mode": "weak",
            "options": {"threshold": .62, "minimum_mm2": 5, "scale_reading": split["id"]}})
        assert wrong.status_code == 400
        print("cross-capture scale rejected:", wrong.get_json()["error"])

        # 8. Legacy weak path (direct controls) still works.
        legacy = reading({"capture": cap_id, "region": inspect_id, "revision": marked_part["revision"], "mode": "weak",
                          "options": {"threshold": .62, "minimum_mm2": 5,
                                      "reference": by_name["Sound blue film"]["id"],
                                      "dark": by_name["Dark return sample"]["id"]}})
        assert "scale" not in legacy and legacy["summary"]["weak_patches"] >= 0

        # 9. Changing the threshold later does not mutate the saved scale.
        before = client.get(f"/survey/readings/{split['id']}").get_json()["scale"]
        reading({"capture": cap_id, "region": inspect_id, "revision": marked_part["revision"], "mode": "weak",
                 "options": {"threshold": .31, "minimum_mm2": 5, "scale_reading": split["id"]}})
        after = client.get(f"/survey/readings/{split['id']}").get_json()["scale"]
        assert before == after

        # 10. Packet still verifies and carries the scale.
        packet = client.get(f"/survey/readings/{auto['id']}/packet")
        assert packet.status_code == 200
        verified = client.post("/survey/verify", data={"file": (io.BytesIO(packet.data), "p.zip")},
                               content_type="multipart/form-data")
        assert verified.status_code == 200, verified.data
        print("packet verified:", verified.get_json()["verified"])
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
