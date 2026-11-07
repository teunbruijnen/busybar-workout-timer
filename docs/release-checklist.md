# Release checklist

Go through this before every release. The hand checks cover what the tests and the emulator can't confirm: how it looks on the LEDs, how it sounds, how the wheel feels. They need a real BUSY Bar and a person.

Install the newest code first: in `js-app`, `npm run build && npm run app:install && npm run app:run`.

## Automated

- [ ] In `js-app`: `npm run typecheck` and `npm test` pass.
- [ ] From the repo root: `python3 tools/jscheck.py --soak 300`: 0 failures. It resets the app's saved settings and Setup values.
- [ ] From the repo root: `python3 tools/hwcheck.py`: 0 screens differ (app stopped).
- [ ] In `js-app`: `npm run release`, then `tar -tvzf dist/*.tgz`: no user or group name.

## By hand

- [ ] A short TABATA (e.g. 0:10 / 0:05 × 2, get-ready 3): READY ticks 3-2-1, phase-end sounds, blinking last digit, progress bar, the completed sound, the recap.
- [ ] FIXED REST and FIXED WORK: the open phase counts up, OK ends it.
- [ ] Pause and resume (START): everything turns grey and the time blinks; it resumes where it left off.
- [ ] Stop early (BACK twice): silent, recap says STOPPED. With ∞ rounds: the completed sound.
- [ ] Hand-timed: the recap's TOTAL matches a stopwatch within 1 s.
- [ ] Sound off under Setup: silent workout.

## Publish

- [ ] The new version in `js-app/package.json`, `js-app/package-lock.json` and `js-app/src/appmeta/manifest.json`.
- [ ] What changed in `CHANGELOG.md`.
- [ ] A GitHub release with `js-app/dist/<id>.tgz` from `npm run release` attached: the README's install step links to the latest release.
