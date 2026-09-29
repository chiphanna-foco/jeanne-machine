// Run with: npm test  (node --test; Node 23.6+ strips TypeScript types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { isAllowedEmail, isAllowedSessionEmail, safeCallback } from "./allowed-email.ts";

test("gmail is rejected", () => {
  assert.equal(isAllowedEmail("someone@gmail.com", true, "turbotenant.com"), false);
  assert.equal(isAllowedEmail("someone@gmail.com", true, "gmail.com"), false);
});

test("verified turbotenant.com is accepted, case-insensitive", () => {
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", true, "turbotenant.com"), true);
  assert.equal(isAllowedEmail("Jeanne@TurboTenant.COM", true, "TurboTenant.com"), true);
});

test("unverified email is rejected", () => {
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", false, "turbotenant.com"), false);
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", undefined), false);
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", "true"), false);
});

test("hd claim is required and must be turbotenant.com", () => {
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", true, "other.com"), false);
  // consumer Google account on a turbotenant.com address: no hd
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", true), false);
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", true, null), false);
});

test("safeCallback keeps same-site paths only", () => {
  assert.equal(safeCallback("/drafts?x=1"), "/drafts?x=1");
  assert.equal(safeCallback("/\\evil.com"), "/");
  assert.equal(safeCallback("//evil.com"), "/");
  assert.equal(safeCallback("https://evil.com/x"), "/");
  assert.equal(safeCallback(undefined), "/");
});

test("look-alike domains are rejected", () => {
  assert.equal(isAllowedEmail("x@evil-turbotenant.com", true, "turbotenant.com"), false);
  assert.equal(isAllowedEmail("x@turbotenant.com.evil.io", true, "turbotenant.com"), false);
  assert.equal(isAllowedEmail("x@sub.turbotenant.com", true, "turbotenant.com"), false);
  assert.equal(isAllowedEmail(null, true, "turbotenant.com"), false);
});

test("session email check", () => {
  assert.equal(isAllowedSessionEmail("a@turbotenant.com"), true);
  assert.equal(isAllowedSessionEmail("a@gmail.com"), false);
  assert.equal(isAllowedSessionEmail(undefined), false);
});
