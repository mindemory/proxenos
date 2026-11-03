// What the root layout needs of the sidebar's width (lib/rail.ts) before any of the page's code has
// loaded: where the reader's pick is kept, and the script that puts it on <html>.

export const RAIL_KEY = "proxenos.rail";

/** Where the sidebar is icons only until the reader picks otherwise. globals.css says the same. */
export const RAIL_NARROW = "(width < 1100px)";

/**
 * Runs in <head> before the page paints, so the sidebar is drawn at the width picked on this
 * device from the first frame. With nothing picked it sets nothing, and the window's width decides.
 */
export const RAIL_SCRIPT = `try{var v=localStorage.getItem("${RAIL_KEY}");if(v==="collapsed"||v==="expanded")document.documentElement.setAttribute("data-rail",v)}catch(e){}`;
