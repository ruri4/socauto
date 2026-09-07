import { chromium } from "playwright-core";

const endpoints = new Set([
    "https://www.tiktok.com/tiktok/web/project/post/v1/",
]);

export function validateTarget(url) {
    const target = new URL(url);
    if (!endpoints.has(target.origin + target.pathname) || target.username || target.password
        || target.hash) {
        throw new Error("invalid signer input");
    }
    return target;
}

export function validateInput({ url, user_agent, executable_path }) {
    const target = validateTarget(url);
    if (!user_agent || !executable_path) throw new Error("invalid signer input");
    return target;
}

async function installSigner(page) {
    for (const script of ["signer.js", "xbogus.js"]) {
        await page.addScriptTag({ path: `${import.meta.dir}/vendor/${script}` });
    }
}

async function signInPage(page, { url, user_agent }) {
    validateTarget(url);
    return await page.evaluate(({ url, user_agent }) => {
        const target = new URL(url);
        if (!target.searchParams.has("verifyFp")) {
            target.searchParams.set("verifyFp",
                `verify_${Date.now().toString(36)}_${crypto.randomUUID().replaceAll("-", "_")}`);
        }
        const signature = window.byted_acrawler.sign({ url: target.toString() });
        target.searchParams.set("_signature", signature);
        const bogus = window.generateBogus(target.searchParams.toString(), user_agent);
        if (typeof signature !== "string" || !signature || typeof bogus !== "string" || !bogus) {
            throw new Error("invalid signer result");
        }
        target.searchParams.set("X-Bogus", bogus);
        return { signed_url: target.toString(), user_agent: navigator.userAgent };
    }, { url, user_agent });
}

export async function sign({ url, user_agent, executable_path }) {
    validateInput({ url, user_agent, executable_path });
    const browser = await chromium.launch({
        executablePath: executable_path,
        headless: true,
        timeout: 15000,
    });
    try {
        const context = await browser.newContext({
            userAgent: user_agent,
            locale: "en-US",
            viewport: { width: 1920, height: 1080 },
            serviceWorkers: "block",
        });
        // Never transmit the signing URL, tokens, or SDK telemetry to a network.
        await context.route("**/*", (route) => route.request().isNavigationRequest()
            ? route.fulfill({ contentType: "text/html", body: "<!doctype html><html></html>" })
            : route.abort());
        const page = await context.newPage();
        await page.goto("https://www.tiktok.com/", { waitUntil: "domcontentloaded" });
        await installSigner(page);
        return await signInPage(page, { url, user_agent });
    } finally {
        await browser.close();
    }
}

if (import.meta.main) {
    try {
        const input = await Bun.stdin.text();
        if (input.length > 32768) throw new Error("input too large");
        console.log(JSON.stringify(await sign(JSON.parse(input))));
    } catch {
        // Never echo Playwright exceptions: they may include tokens or signed URLs.
        console.error("tiktok signer failed");
        process.exitCode = 1;
    }
}
