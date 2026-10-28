# Vendored front-end code

`htm-preact-standalone.mjs` is `htm/preact/standalone.mjs` from htm 3.1.1 (npm), unmodified: htm (Apache
License 2.0, `LICENSE-htm`) bundled with Preact (MIT License, Copyright (c) 2015-present Jason Miller). It is
served from the console itself so that the console works without internet access; there is no build step.

`hds/` is the distributed build of the NASA Horizon Design System, `@nasa-hds/core` 0.10.0 (npm): `css/hds.min.css`
(HDS on USWDS 3, with its fonts and the images and icon sprites the stylesheet references), unmodified. HDS is
released under the CC0 1.0 public domain dedication (`hds/LICENSE.md`); the Inter, Public Sans and DM Mono fonts
are under the SIL Open Font License 1.1 (license text next to each font). The package's NASA branding folder,
logo and favicons are deliberately left out: NASA's insignia and logotype are trademarks that CC0 does not
cover, and the console does not use them.
