# Workout Timer: the JavaScript app

The workout timer as a JavaScript app that runs on the BUSY Bar. Behaviour: [../SPEC.md](../SPEC.md). Working on it: [../CLAUDE.md](../CLAUDE.md). The firmware's runtime rules: [AGENTS.md](AGENTS.md).

To build it yourself you need Node 24, and a bar connected over USB to install it. To only use the timer, install the release: see [../README.md](../README.md).

```sh
npm install
npm run typecheck
npm test
npm run build         # dist/app.teunbruijnen.workout_timer.tgz
npm run app:install
npm run app:run
```

`npm test` runs `../app.py` as the reference, so it needs `python3`.

For a release: `npm run release`. It builds `dist/<id>.tgz` and blanks the build machine's user and group in it.
