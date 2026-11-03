import {exportBlob} from "./export.mjs";
let address = null;
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== "offscreen" || sender.id !== chrome.runtime.id) return;
  if (message.action === "build") {
    (async () => {
      const reply = await chrome.runtime.sendMessage({target: "worker", action: "export-data"});
      if (reply.error) throw Error(reply.error);
      if (address) URL.revokeObjectURL(address);
      address = URL.createObjectURL(exportBlob(reply.saved)); respond({url: address});
    })().catch(error => respond({error: error.message}));
    return true;
  }
});
