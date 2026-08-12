const test = require("node:test");
const assert = require("node:assert/strict");
const {
  categoryMatches,
  compareCards,
  matchesSearch,
  normaliseSearch,
  readSaved,
  searchScore,
  visiblePage,
  writeSaved,
} = require("../../site/static/app.js");

test("corrupt local storage fails safely", () => {
  const storage = { getItem: () => "not-json" };
  assert.deepEqual([...readSaved(storage, "saved")], []);
});

test("saved role storage is local and round-trips", () => {
  let value = null;
  const storage = {
    getItem: () => value,
    setItem: (_key, next) => { value = next; },
  };
  assert.equal(writeSaved(storage, "saved", new Set(["role-2", "role-1"])), true);
  assert.deepEqual([...readSaved(storage, "saved")], ["role-2", "role-1"]);
});

test("evidence sorting uses explicit strength rather than alphabetical status", () => {
  const verified = { dataset: { evidence: "3" } };
  const likely = { dataset: { evidence: "2" } };
  assert.ok(compareCards("evidence", verified, likely) < 0);
});

test("major category quick filters use category data", () => {
  assert.equal(categoryMatches("Legal and Regulatory", ["risk", "legal", "compliance"]), true);
  assert.equal(categoryMatches("Geospatial Analysis and GIS", ["health", "pharmaceutical"]), false);
});

test("large result sets render in bounded pages without losing roles", () => {
  const roles = Array.from({ length: 757 }, (_, index) => `role-${index}`);
  assert.equal(visiblePage(roles, 100).length, 100);
  assert.equal(visiblePage(roles, 800).length, 757);
  assert.deepEqual(visiblePage(roles, -1), []);
});

test("search is case, punctuation, accent and word-order tolerant", () => {
  assert.equal(normaliseSearch("A&O — Crédit"), "a and o credit");
  assert.equal(matchesSearch("Private Credit Intern", "credit private"), true);
  assert.equal(matchesSearch("The Carlyle Group", "carlyle group"), true);
  assert.equal(matchesSearch("Blackstone", "BlackRock"), false);
});

test("exact title and company matches rank ahead of broad description matches", () => {
  const exact = {
    dataset: {
      title: "Private Credit Intern",
      employer: "The Carlyle Group",
      search: "Private Credit Intern The Carlyle Group",
    },
  };
  const broad = {
    dataset: {
      title: "Finance Assistant",
      employer: "Example Employer",
      search: "Finance Assistant supporting a private credit team",
    },
  };
  assert.ok(searchScore(exact, "Private Credit Intern", "Carlyle") > searchScore(broad, "Private Credit Intern", "Carlyle"));
});
