import { expect, test } from "bun:test";
import { sign } from "./sign.js";

test("rejects non-publish URLs before browser launch", async () => {
    await expect(sign({ url: "https://evil.test/", user_agent: "test", executable_path: "/missing" }))
        .rejects.toThrow("invalid signer input");
});

test("stdin failures have credential-safe diagnostics", async () => {
    const child = Bun.spawn([process.execPath, "run", `${import.meta.dir}/sign.js`], {
        stdin: new Blob([JSON.stringify({ url: "secret-session" })]), stdout: "pipe", stderr: "pipe",
    });
    expect(await child.exited).toBe(1);
    expect(await new Response(child.stdout).text()).toBe("");
    expect(await new Response(child.stderr).text()).toBe("tiktok signer failed\n");
});

const binary = process.env.SOCAUTO_TIKTOK_CHROMIUM_BINARY;
test.skipIf(!binary)("offline Chromium creates signatures with the requested UA", async () => {
    const url = "https://www.tiktok.com/tiktok/web/project/post/v1/?aid=1988&msToken=test-token";
    const result = await sign({ url, user_agent: "socauto-test-agent", executable_path: binary });
    const query = new URL(result.signed_url).searchParams;
    expect(query.get("msToken")).toBe("test-token");
    expect(query.get("_signature").length).toBeGreaterThan(10);
    expect(query.get("X-Bogus").length).toBeGreaterThan(10);
    expect(query.get("verifyFp")).toStartWith("verify_");
    expect(result.user_agent).toBe("socauto-test-agent");
}, 30000);
