// Run with: npm test  (node --test; Node 23.6+ strips TypeScript types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { isAllowedEmail, isAllowedSessionEmail } from "./allowed-email.ts";

test("gmail is rejected", () => {
  assert.equal(isAllowedEmail("someone@gmail.com", true), false);
  assert.equal(isAllowedEmail("someone@gmail.com", true, "gmail.com"), false);
});

test("verified turbotenant.com is accepted, case-insensitive", () => {
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", true, "turbotenant.com"), true);
  assert.equal(isAllowedEmail("Jeanne@TurboTenant.COM", true), true);
});

test("unverified email is rejected", () => {
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", false, "turbotenant.com"), false);
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", undefined), false);
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", "true"), false);
});

test("hd claim, when present, must be turbotenant.com", () => {
  assert.equal(isAllowedEmail("jeanne@turbotenant.com", true, "other.com"), false);
});

test("look-alike domains are rejected", () => {
  assert.equal(isAllowedEmail("x@evil-turbotenant.com", true), false);
  assert.equal(isAllowedEmail("x@turbotenant.com.evil.io", true), false);
  assert.equal(isAllowedEmail("x@sub.turbotenant.com", true), false);
  assert.equal(isAllowedEmail(null, true), false);
});

test("session email check", () => {
  assert.equal(isAllowedSessionEmail("a@turbotenant.com"), true);
  assert.equal(isAllowedSessionEmail("a@gmail.com"), false);
  assert.equal(isAllowedSessionEmail(undefined), false);
});
