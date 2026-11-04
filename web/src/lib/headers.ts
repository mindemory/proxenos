// The header every request the page makes that changes something carries, beside the JSON body's
// type. A page on another site can't send a custom header here without a CORS preflight, which
// this server never answers, so the guard (web/src/lib/guard.ts) refuses any other request that
// isn't a read without it. No file access, so the server and the page share it.

export const PAGE_HEADER = "x-proxenos";

/** The headers of a JSON request from the page. */
export const JSON_HEADERS = { "content-type": "application/json", [PAGE_HEADER]: "1" } as const;
