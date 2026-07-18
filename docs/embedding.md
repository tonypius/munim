# Embedding Munim in your app

Munim is designed to be a host app's classification engine. Two commands
form the entire integration surface — no server, no SDK, no library binding.

## classify: JSONL in, JSONL out, no side effects

```bash
echo '{"date":"2026-06-01","amount":340,"direction":"debit",
       "description":"UPI-SWIGGY8102@okaxis-513324498812"}' | munim classify
```

Each output line echoes the input plus: `merchant_norm`, `payee_handle`,
`category`, `confidence`, `stage` (provenance), `status`, `is_transfer`,
`is_recurring`. It reads the user's memory and the community dictionary but
persists nothing (add `--store` to also write to the DB). Invoke once per
batch, not per transaction.

Node example (the shape of a Cashew bridge):

```ts
import { spawn } from "child_process";

export async function munimClassify(txns: object[]): Promise<object[]> {
  const proc = spawn("munim", ["classify"]);
  proc.stdin.write(txns.map(t => JSON.stringify(t)).join("\n"));
  proc.stdin.end();
  let out = "";
  for await (const chunk of proc.stdout) out += chunk;
  return out.trim().split("\n").map(l => JSON.parse(l));
}
```

## learn: the feedback channel

When a user confirms a category in YOUR review UI, tell the engine:

```bash
munim learn "THIRD WAVE COFFEE" "Dining"          # merchant
munim learn "RAMESH KUMAR" "Family & Friends" --payee   # person
```

Pure memory write; by default also resolves matching unconfirmed stored
transactions. If you skip this call, the engine never improves from your
app's usage — the integration is cosmetic. Wire it or don't integrate.

## Division of labor

Your app owns: ingestion UI, review UI, analytics, budgets, storage of its
own richer records. Munim owns: normalization (region packs), memory,
dictionary, fallback classification, provenance. Map Munim's flat categories
to your app's taxonomy in a config file on your side; treat `status !=
'confirmed'` output as suggestions to surface, never as ground truth.
