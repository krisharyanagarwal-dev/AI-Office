const fs = require("fs");
const HIVE = process.env.OPENALICE_HIVE;

const realSetInterval = global.setInterval;
let created = null;
global.setInterval = (fn, ms) => {
  const h = realSetInterval(fn, ms);
  if (ms === 60000) created = h;
  return h;
};
const cost = require(HIVE + "/lib/llm/cost.js");
global.setInterval = realSetInterval;

fs.writeSync(1, "  interval created at import : " + (created ? "yes" : "no") + "\n");
fs.writeSync(1, "  hasRef() after unref      : " + (created ? created.hasRef() : "n/a") + "  (false = will not hold the loop)\n");
fs.writeSync(1, "  still a live Timer object : " + (created && typeof created.refresh === "function") + "\n");

// Keep the process alive independently of the module's timer, then confirm
// the unref-ed timer still fires (unref only removes the hold, not the schedule).
const keep = realSetInterval(() => {}, 1000);
let fired = 0;
const spy = realSetInterval(() => {}, 60000);
spy.unref();

realSetInterval(() => {
  fired++;
  fs.writeSync(1, "  unref-ed timer still fires: yes (fired " + fired + "x while loop was held by another source)\n");
  fs.writeSync(1, "  recordCost callable       : " + (typeof cost.recordCost === "function") + "\n");
  fs.writeSync(1, "  getters intact            : " +
    (typeof cost.getAgentDailyCost === "function" && typeof cost.getTotalCosts === "function") + "\n");
  clearInterval(keep);
  clearInterval(spy);
}, 1500);
