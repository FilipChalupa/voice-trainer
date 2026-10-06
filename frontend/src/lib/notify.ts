/** Tells the person that something long has finished while they were elsewhere: a browser notification (once
 *  they allowed it) and a mark in the tab title until the tab is looked at again. */
const PREF = "voice-trainer.notify";
const base = document.title;
let marked = false;

export function notificationsAllowed(): boolean {
  try {
    return typeof Notification !== "undefined" && Notification.permission === "granted" && localStorage.getItem(PREF) !== "0";
  } catch {
    return false;
  }
}

export function notificationsSupported(): boolean {
  return typeof Notification !== "undefined";
}

/** Asks for permission when needed; returns whether notifications are on afterwards. */
export async function setNotifications(on: boolean): Promise<boolean> {
  try {
    localStorage.setItem(PREF, on ? "1" : "0");
  } catch {
    /* private mode */
  }
  if (!on || !notificationsSupported()) return false;
  if (Notification.permission !== "granted") await Notification.requestPermission();
  return notificationsAllowed();
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && marked) {
    marked = false;
    document.title = base;
  }
});

export function notifyDone(title: string, body?: string): void {
  if (document.hidden) {
    marked = true;
    document.title = `✓ ${title}`;
  }
  if (notificationsAllowed() && document.hidden) {
    try {
      new Notification(title, { body, tag: "voice-trainer" });
    } catch {
      /* some browsers allow notifications only from a service worker */
    }
  }
}
