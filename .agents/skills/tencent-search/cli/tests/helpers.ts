import { spawnSync } from "node:child_process"

export interface CliResult {
  code: number
  stdout: string
  stderr: string
}

export function runCli(args: string[]): CliResult {
  const r = spawnSync("bun", ["run", "src/cli.ts", ...args], {
    encoding: "utf-8",
    timeout: 90_000,
  })
  return { code: r.status ?? 1, stdout: r.stdout ?? "", stderr: r.stderr ?? "" }
}

/* eslint-disable @typescript-eslint/no-explicit-any */
export function parseJSON(s: string): any {
  return JSON.parse(s)
}
