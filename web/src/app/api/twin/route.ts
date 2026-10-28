// The profile's earlier path, kept so anything that still calls it gets the same answer.
// The page itself uses /api/profile.
export { GET } from "../profile/route";

export const dynamic = "force-dynamic";
