let timer: number | undefined;

/** Short-lived status message, e.g. after copying the share link. */
export function showToast(message: string, durationMs = 2500): void {
  const toast = document.getElementById('toast');
  if (!toast) {
    return;
  }
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    toast.hidden = true;
  }, durationMs);
}
