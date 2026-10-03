# Maya capture validation

Validated locally with Maya 2027 and bundled Arnold on Windows. These records concern the original installed tool, not a fresh-machine installation of this source archive.

- Fixed-camera projection, normalized camera transforms and source-frame/time mapping.
- Animation bounds scanning across the sampled timeline and two-ring camera creation.
- Arnold preview rendering, PNG decoding, RGBA/straight-alpha export and complete dataset generation.
- Resume checks for damaged images and incompatible capture settings.
- Render-setting restoration and workbench handoff in isolated test fixtures.
- English panel layout, renamed sections and Use Current Timeline control.

Tests are supplied under tests/. Several need Maya's Python or a separate Maya GUI instance and create their own scenes. Test output is written to test-results/ and is excluded from the publication archive. Start with tests/maya_integration.py under the Maya 2027 mayapy executable; the HUST reader check additionally requires the separately installed training backend.

Successful capture does not establish production fluid/fracture reconstruction quality, clean refraction, convergence or VR performance. Cache and preview your own material/lighting/animation before a full capture.
