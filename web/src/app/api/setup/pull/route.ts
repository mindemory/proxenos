import { startJob, stopJob } from "@/lib/connect";
import { NO_STORE, readLocalJson, rejectNonLocal } from "@/lib/guard";
import { runJob } from "@/lib/runJobs";

export const dynamic = "force-dynamic";

/** As the name of a model in Ollama's registry: gemma4:e4b, or a user's own, library/name:tag. */
const NAME = /^[A-Za-z0-9._:/-]{1,100}$/;

/** As a Hugging Face repo: mlx-community/gemma-4-e4b-it-4bit. */
const REPO = /^[A-Za-z0-9._-]{1,60}\/[A-Za-z0-9._-]{1,100}$/;

/** GET /api/setup/pull: the latest model download, running (its message says how far along) or how it ended. Cheap enough to poll. */
export async function GET(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json({ job: runJob("model") }, { headers: NO_STORE });
}

/**
 * POST /api/setup/pull {name, as} downloads a model through Ollama (or, with {repo, as}, one Proxenos runs itself, from Hugging Face) in the background, one at a time, and answers at
 * once. `as` is "starter" (the model to use first) or "main" (the model that writes, the small one before it
 * keeping the light jobs). The model comes from Ollama's registry; nothing of yours is sent.
 */
export async function POST(req: Request) {
  const parsed = await readLocalJson(req);
  if ("denied" in parsed) return parsed.denied;
  const { name, repo, as } = parsed.body;
  if (as !== "starter" && as !== "main") {
    return Response.json({ error: "as must be starter or main." }, { status: 400 });
  }
  // A model Proxenos runs itself (proxenos model get): downloaded from Hugging Face, with mlx-lm.
  if (repo !== undefined) {
    if (typeof repo !== "string" || !REPO.test(repo)) {
      return Response.json({ error: "That isn't a model's repo, e.g. mlx-community/gemma-4-e4b-it-4bit." }, { status: 400 });
    }
    const job = await startJob("model", ["model", "get", "--as", as, "--", repo], repo);
    if (!job) return Response.json({ error: "A model is being downloaded already." }, { status: 409 });
    return Response.json({ job: runJob("model") }, { status: 202, headers: NO_STORE });
  }
  if (typeof name !== "string" || !NAME.test(name)) {
    return Response.json({ error: "That isn't a model's name, e.g. gemma4:e4b." }, { status: 400 });
  }
  // The options go before "--", so nothing in the name is taken for one.
  const job = await startJob("model", ["model", "pull", "--as", as, "--", name], name);
  if (!job) return Response.json({ error: "A model is being downloaded already." }, { status: 409 });
  return Response.json({ job: runJob("model") }, { status: 202, headers: NO_STORE });
}

/** DELETE /api/setup/pull stops the download. Ollama keeps what it has, and carries on from there next time. */
export async function DELETE(req: Request) {
  const denied = rejectNonLocal(req);
  if (denied) return denied;
  return Response.json({ stopped: stopJob("model") }, { headers: NO_STORE });
}
