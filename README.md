# SignFace Desk

A local survey workbench for photographs of existing wayfinding panels. Mark the photograph's measured plane before comparing positions. Workflows include plane registration, visible panel outline, finish-loss candidates, a measured luminance transect, frozen relative-return scales, weak-return footprints reopened through a saved scale, letter/background contrast, Lab color, exposure support, paired visibility and surface scuff candidates. Saved readings retain the source photographs, measurements and PNG overlay. Export a CSV or a ZIP with the source photos and verify the members on another local instance.

```sh
docker compose up --build
```

Open the address shown by Compose or http://127.0.0.1:19996. Set `SIGNFACE_PORT` for another local port. Shut down with Ctrl+C. The named volume holds the inspection records and source objects. Tools run on the CPU. They accept PNG, JPEG and TIFF to 18 MB and 12 megapixels, at most 12 captures and 36 marks per panel. Upload only photos with known orientation and stable exposure when comparing relative readings. The plane is at most 1450 pixels over its long edge, so detail below one resampled pixel is unresolved. Exposure clipping and alpha holes consume no measurable pixels. Relative return supplies no calibrated luminance, sign certification, OCR or automatic field maintenance decision.

### Frozen return scales

A night capture can lose light unevenly across its face. On **Relative return** mark sound return and dark references on the left and, when needed, a second pair on the right, plus known-good check film on each side. Check film only validates the scale: it is never used as a control. Enter the maximum deviation each check film may show from a normal reading of 1.0 on the scale.

- **Common reference** joins both sides and the middle band with one pair of controls.
- **Side-specific references** normalize each half against its own controls; the middle band that cannot be assigned to either side is left unresolved and counted separately.
- **Auto** evaluates both. A scheme is rejected if either check film falls outside its tolerance. If both pass, the scale with the smaller worst check deviation is adopted; a tie keeps the common scale because it covers the middle band.

The accepted controls, bands, check results and observed range are frozen inside the saved reading and shown in its report. Later threshold changes or new measurements never alter a saved scale. On **Weak return patches**, choose a saved scale and draw a small inspection window: dark blocks are found using that scale's frozen references and the capture's observed range, while positions with no evidence stay separate. A scale can only be reopened on its original photograph; marking sound and dark references directly remains available for readings that do not use a frozen scale.

Choose **Load synthetic sample** for a pair of invented day and night photographs whose night panel carries left and right control pairs and check film. Open **Measure**, choose **Relative return**, choose the night photo, its two sides of controls and the check film tolerances, and save. Reopen the saved inspection under **Weak return patches** and download the packet. The **Image preparation** workspace can produce a new input photo to import as a separate capture without changing a saved reading.
