import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";


test("packed SDK installs and imports in a clean project", () => {
  const root = process.cwd();
  const temporaryRoot = mkdtempSync(join(tmpdir(), "wavemind-sdk-"));
  const packageDirectory = join(temporaryRoot, "packages");
  const consumerDirectory = join(temporaryRoot, "consumer");
  const npmOptions = {
    shell: process.platform === "win32",
  };
  try {
    mkdirSync(packageDirectory);
    mkdirSync(consumerDirectory);
    const packOutput = execFileSync(
      "npm",
      ["pack", "--json", "--pack-destination", packageDirectory],
      {
        cwd: root,
        encoding: "utf8",
        ...npmOptions,
      },
    );
    const packed = JSON.parse(packOutput);
    assert.equal(packed.length, 1);
    const tarball = join(packageDirectory, packed[0].filename);

    writeFileSync(
      join(temporaryRoot, "package-check.json"),
      JSON.stringify(packed[0], null, 2),
    );
    execFileSync("npm", ["init", "-y"], {
      cwd: consumerDirectory,
      stdio: "ignore",
      ...npmOptions,
    });
    execFileSync("npm", ["pkg", "set", "type=module"], {
      cwd: consumerDirectory,
      stdio: "ignore",
      ...npmOptions,
    });
    execFileSync("npm", ["install", "--ignore-scripts", tarball], {
      cwd: consumerDirectory,
      stdio: "ignore",
      ...npmOptions,
    });
    writeFileSync(
      join(consumerDirectory, "smoke.mjs"),
      [
        'import { WaveMindClient, WaveMindHTTPError } from "@wavemind/http";',
        'const client = new WaveMindClient({ baseUrl: "http://127.0.0.1:8000" });',
        'if (client.baseUrl !== "http://127.0.0.1:8000") process.exit(2);',
        "if (!(WaveMindHTTPError.prototype instanceof Error)) process.exit(3);",
      ].join("\n"),
    );
    execFileSync(process.execPath, ["smoke.mjs"], {
      cwd: consumerDirectory,
      stdio: "inherit",
    });

    const installedPackage = JSON.parse(
      readFileSync(
        join(
          consumerDirectory,
          "node_modules",
          "@wavemind",
          "http",
          "package.json",
        ),
        "utf8",
      ),
    );
    assert.equal(installedPackage.name, "@wavemind/http");
    assert.equal(installedPackage.types, "./dist/index.d.ts");
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});
