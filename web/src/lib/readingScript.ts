// What the root layout needs of the reading settings (lib/reading.ts) before any of the page's
// code has loaded: where they're kept, the device's own asks, and the script that applies them.

export const READING_KEY = "proxenos.reading";

/** The device's own asks, which the settings here add to. */
export const DEVICE_CONTRAST = "(prefers-contrast: more)";
export const DEVICE_LIGHT = "(prefers-color-scheme: light)";
export const DEVICE_CALM = "(prefers-reduced-motion: reduce)";

/**
 * Runs in <head> before the page paints, so a reader's settings show from the first frame rather
 * than after a flash of the defaults. The same rules as `readingAttributes`, written out by hand
 * because it runs before the page's code.
 */
export const READING_SCRIPT = `try{var r=JSON.parse(localStorage.getItem("${READING_KEY}")||"{}")||{},d=document.documentElement,m=function(q){return matchMedia(q).matches};if(r.size==="large"||r.size==="larger")d.setAttribute("data-text",r.size);if(r.face==="hyperlegible")d.setAttribute("data-face","hyperlegible");if(r.spacing==="relaxed")d.setAttribute("data-spacing","relaxed");if(r.theme==="light"||(r.theme==="system"&&m("${DEVICE_LIGHT}")))d.setAttribute("data-theme","light");if(r.contrast===true||m("${DEVICE_CONTRAST}"))d.setAttribute("data-contrast","more");if(r.calm===true)d.setAttribute("data-motion","less")}catch(e){}`;
