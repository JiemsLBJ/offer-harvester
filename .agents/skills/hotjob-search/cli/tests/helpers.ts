import { spawnSync } from "node:child_process"

export function runCli(args: string[]): { code: number; stdout: string; stderr: string } {
  const result = spawnSync("bun", ["run", "src/cli.ts", ...args], { encoding: "utf-8", timeout: 90_000 })
  return { code: result.status ?? 1, stdout: result.stdout ?? "", stderr: result.stderr ?? "" }
}

export function parseJSON(value: string): any {
  return JSON.parse(value)
}
