export async function executeCli(args) {
  if (typeof Bun !== "undefined") {
    const command = process.env.MEMORYHUB_PYTHON
      ? [process.env.MEMORYHUB_PYTHON, "-m", "memoryhub_cli", ...args]
      : ["memoryhub", ...args]
    const child = Bun.spawn(command, { stdout: "pipe", stderr: "pipe" })
    return (await new Response(child.stdout).text()).trim()
  }
  const { execFile } = await import("node:child_process")
  return await new Promise((resolve) => execFile("memoryhub", args, { timeout: 15000 }, (error, stdout, stderr) => {
    if (error?.code === "ENOENT") {
      execFile(process.env.MEMORYHUB_PYTHON || "python", ["-m", "memoryhub_cli", ...args], { timeout: 15000 }, (_fallbackError, fallbackOut, fallbackErr) => resolve(String(fallbackOut || fallbackErr).trim()))
      return
    }
    resolve(String(stdout || stderr).trim())
  }))
}
