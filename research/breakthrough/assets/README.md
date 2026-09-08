# Research artwork and figure sources

The research pages distinguish illustration, simulation and measured evidence.
No asset in this directory depicts a built WaveMind quantum sensor.

## Concept cover

`quantum-sensing-concept.png` is AI-generated editorial artwork, produced with
the built-in ImageGen tool on 2026-09-08. It is not a laboratory photograph,
an NV-center schematic, a device design or evidence of a successful experiment.
The generated file was copied into the repository without image editing.

SHA-256: `20f97f9b1ab68bf846affa9c5683a547faef37c63950785fd6cd1629db65d6db`.

Required adjacent caption: “Conceptual AI-generated illustration, not a
photograph of a built sensor or a completed experiment.” Localize this caption
when using it on the Russian page. Keep descriptive alt text as well.

<details>
<summary>Generation prompt and provenance</summary>

Use case: scientific-educational. Asset type: photographic-style editorial cover for an open quantum sensing RESEARCH repository, not a real device photograph. Generate ONE landscape image, 16:9, no typography or logos. Subject: an evocative, physically plausible macro still-life of a tiny transparent diamond-like crystal resting on a precision-machined copper mount over a few fine copper circuit traces. A faint controlled optical illumination touches the crystal; no visible fantasy beam, no plasma, no floating atoms, no sci-fi holograms. Composition: quiet close-up, shallow depth of field, the small crystal and mount in the right-center with ample calm negative space on the left for surrounding editorial page copy (do not render text). Warm off-white laboratory tabletop, dark graphite accents, copper-orange material highlights. Lighting: museum-quality scientific editorial photography, soft raking light, restrained specular reflections, real machined metal and glass texture, exceptionally detailed, sophisticated rather than a stock-photo lab. No people, no fake instruments or readings, no claims of success, no company or institution marks. This is explicitly conceptual artwork illustrating a research direction; it must not impersonate photographic evidence of a completed prototype or experiment.

Generation mode: native ImageGen, one new image, no reference images.
The prompt requests an editorial concept, not specific physical apparatus.
Numerical results, labels and scientific charts must not be generated this way.

</details>

## Numerical figures

The user selected [Cathryn Lavery's diagram-design](https://github.com/cathrynlavery/diagram-design).
Upstream version 2.6, source revision
`dcd9317ed9ec7477b20005544f36e3313664d815`, [MIT license](LICENSE.diagram-design.txt).
Its first-project style choice is pending; no chart has been represented as
finished or exported before that choice. The illustration above is separate
from this diagram workflow.

The [figure contract](FIGURE_CONTRACT.md) defines questions, quantities,
source data, omissions and export checks before drawing. Graphical style
must not change a numerical value, hide a negative result or imply hardware
validation. The current guides use source-backed tables while chart styling
awaits confirmation.

Numerical inputs are already reproducible independently of that style choice:

```sh
python research/breakthrough/assets/build_figure_data.py --check
python -m pytest research/breakthrough/assets -q -p no:cacheprovider
```

[`figure-data.json`](figure-data.json) contains the eight selected bar values,
257 exact-formula samples for each of the three commanded controls, resource
costs and source hashes. The generator validates the complete run manifest
before reading results. It renders no diagram and implies no style approval.

[Presentation QA](presentation_validation.json) records the 42-test scoped
run and the local English/Russian desktop/mobile preview checks. That preview
is not a live GitHub rendering and the full product suite was not rerun.
