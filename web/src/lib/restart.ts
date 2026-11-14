// The backend restarts after a plugin change (only the backend: the web app, the links and the instances keep
// running). This waits until it is back: first until it stops answering (or a few seconds pass), then until it
// answers again.

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const answers = () =>
  fetch("/healthz", { cache: "no-store" })
    .then((r) => r.ok)
    .catch(() => false);

export async function waitForBackend(seconds = 90): Promise<boolean> {
  for (let i = 0; i < 8 && (await answers()); i++) await pause(750);
  for (let i = 0; i < seconds; i++) {
    if (await answers()) return true;
    await pause(1000);
  }
  return false;
}
