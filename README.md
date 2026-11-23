# SignFace Desk

A local survey workbench for photographs of existing wayfinding panels. Mark the photograph's measured plane before comparing positions. Workflows include plane registration, visible panel outline, finish-loss candidates, a measured luminance transect, same-exposure relative return, weak-return footprints, letter/background contrast, glyph outline adoption from two candidate character outlines, character-edge contrast along the adopted glyph, Lab color, exposure support, paired visibility and surface scuff candidates. Saved readings retain the source photographs, measurements and PNG overlay. Export a CSV or a ZIP with the source photos and verify the members on another local instance.

```sh
docker compose up --build
```

Open the address shown by Compose or http://127.0.0.1:19996. Set `SIGNFACE_PORT` for another local port. Shut down with Ctrl+C. The named volume holds the inspection records and source objects. Tools run on the CPU. They accept PNG, JPEG and TIFF to 18 MB and 12 megapixels, at most 12 captures and 36 marks per panel. Upload only photos with known orientation and stable exposure when comparing relative readings. The plane is at most 1450 pixels over its long edge, so detail below one resampled pixel is unresolved. Exposure clipping and alpha holes consume no measurable pixels. Relative return is computed against two marked controls in the same photo. It supplies no calibrated luminance, sign certification, OCR or automatic field maintenance decision.

Choose **Load synthetic sample** for a pair of invented day and night photographs. Open **Measure**, choose **Relative return**, choose the night photo and the marked sound and dark references, and save. Reopen the saved inspection and download the packet. The **Image preparation** workspace can produce a new input photo to import as a separate capture without changing a saved reading.
