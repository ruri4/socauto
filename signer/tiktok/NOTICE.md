# TikTok signing assets

The HTTP sequence and signing integration are adapted from
[makiisthenes/TiktokAutoUploader](https://github.com/makiisthenes/TiktokAutoUploader),
commit `d29b4366edf0de705e87f265298a06b64a00d7dc`, under the accompanying MIT license.
Upstream attributes its browser signer to carcabot/tiktok-signature.

`vendor/signer.js` is the unchanged upstream `javascript/signer.js`.
`vendor/xbogus.js` is generated with Bun's minifier from upstream `javascript/xbogus.js`,
with its first line changed from `var window = null;` to `var window = globalThis;`.
It is bundled as an IIFE through an entry file importing `./javascript/xbogus.js`:
`bun build browser-xbogus.js --target browser --format iife --minify --outfile xbogus.js`.
The import entry is necessary to execute Bun's CommonJS wrapper rather than merely define it.
Both assets execute only in a disposable, network-blocked browser context.

The upstream webmssdk.js is deliberately excluded: it embeds historical session cookies
and is unnecessary for these two local signing functions. No upstream cookies are used.
We also omit random user-agent selection, hardcoded verifyFp, recursive wrappers,
and the asynchronous script-loading race in the upstream runner.

Local signature generation is not evidence that TikTok currently accepts the signatures.
These private interfaces require an opt-in live upload test.

Vendored SHA-256 checksums:

- `signer.js`: `21b0278ba95d51fb55b8608116b462f80324021855cd61026c22b09cd8cce3b6`
- `xbogus.js`: `cf2d42d9373517d3973c82e5d6ec08cf3d7467ccbd6964d0a7454062894e5b3b`
