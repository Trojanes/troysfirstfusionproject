# Third-party notices

## Deepnest-next

CabinetNC embeds Deepnest-next v1.5.6, pinned at commit
`6a608e50c35df41dba0b264fa8124c3bb427f8ed`.

Source: https://github.com/deepnest-next/deepnest

Deepnest-next contains components under multiple licenses. The authoritative
license texts and component list are retained in
`nesting/vendor/deepnest-next/LICENSE`,
`nesting/vendor/deepnest-next/LICENSES.md`, relevant source headers, and
dependency package directories.

Important components used by the nesting bridge include:

- `main/deepnest.js`: GPL-3.0 per the upstream source header/component list.
- `@deepnest/svg-preprocessor`: AGPL-3.0-only.
- `@deepnest/calculate-nfp`: MIT.
- Other Deepnest files and bundled dependencies: MIT, Boost, and additional
  licenses recorded by their upstream distributions.

Distribution of a build containing these components must comply with all
applicable license obligations, including corresponding-source and notice
requirements where triggered. This notice is informational and is not legal
advice.

## Sparrow / jagua-rs (optional quality engine)

CabinetNC can invoke an optional, separately packaged native Sparrow bridge for
high-quality irregular nesting. CabinetNC does not download this binary at
runtime and continues to work with its built-in engine when it is absent.

- Sparrow: https://github.com/JeroenGar/sparrow
- jagua-rs: https://github.com/JeroenGar/jagua-rs
- sparroWASM reference: https://github.com/JeroenGar/sparroWASM

Sparrow's repository records its own license; jagua-rs and sparroWASM are
distributed under Mozilla Public License 2.0. A distributed Sparrow bridge must
retain the corresponding upstream license texts and source-code obligations.
