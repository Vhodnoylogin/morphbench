/* Morphbench add-on API v1. Classic script; no imports or host-page internals. */
;(function (global) {
  "use strict";

  const API_VERSION = 1;
  const REQUEST_TIMEOUT_MS = 10000;
  const pending = new Map();
  const listeners = new Map();
  let sequence = 0;
  let connection = null;
  const nonce = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);

  function failure(code, message) {
    const error = new Error(message);
    error.code = code;
    return error;
  }

  function object(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function settle(id, error, result) {
    const item = pending.get(id);
    if (!item) return;
    pending.delete(id);
    global.clearTimeout(item.timer);
    if (error) item.reject(error); else item.resolve(result);
  }

  global.addEventListener("message", function (event) {
    if (event.source !== global.parent) return;
    const message = event.data;
    if (!object(message)) return;
    if (message.type === "morphbench-addon:response") {
      if (typeof message.id !== "string" || !pending.has(message.id)) return;
      if (message.apiVersion !== API_VERSION) {
        settle(message.id, failure("incompatibleApi", "Unsupported Morphbench add-on API version."));
      } else if (Object.prototype.hasOwnProperty.call(message, "error")) {
        const error = message.error;
        settle(message.id, object(error) && typeof error.code === "string" &&
          typeof error.message === "string"
          ? failure(error.code, error.message)
          : failure("invalidResponse", "Invalid Morphbench error response."));
      } else if (Object.prototype.hasOwnProperty.call(message, "result")) {
        settle(message.id, null, message.result);
      } else {
        settle(message.id, failure("invalidResponse", "Invalid Morphbench response."));
      }
    } else if (message.type === "morphbench-addon:event" &&
               message.apiVersion === API_VERSION && typeof message.event === "string") {
      const handlers = listeners.get(message.event);
      if (!handlers) return;
      for (const handler of Array.from(handlers)) {
        // One consumer must not prevent the other subscribers from seeing an event.
        try { handler(message.data); } catch (error) { global.console.error(error); }
      }
    }
  });

  function request(method, params) {
    if (params === undefined) params = {};
    if (typeof method !== "string" || !method || !object(params)) {
      return Promise.reject(failure("invalidParams", "A method name and parameters object are required."));
    }
    if (global.parent === global) {
      return Promise.reject(failure("notConnected", "Open this add-on inside Morphbench."));
    }
    return new Promise(function (resolve, reject) {
      const id = nonce + ":" + (++sequence);
      const timer = global.setTimeout(function () {
        settle(id, failure("timeout", "Morphbench did not respond within 10 seconds."));
      }, REQUEST_TIMEOUT_MS);
      pending.set(id, { resolve: resolve, reject: reject, timer: timer });
      try {
        global.parent.postMessage({
          type: "morphbench-addon:request", apiVersion: API_VERSION,
          id: id, method: method, params: params
        }, "*");
      } catch (error) {
        settle(id, failure("invalidParams", "Request parameters cannot be sent: " + error.message));
      }
    });
  }

  function connect() {
    if (!connection) {
      connection = request("host.info").then(function (info) {
        if (!object(info) || info.apiVersion !== API_VERSION) {
          throw failure("incompatibleApi", "Unsupported Morphbench add-on API version.");
        }
        return info;
      }).catch(function (error) {
        connection = null;
        throw error;
      });
    }
    return connection;
  }

  function on(event, handler) {
    if (typeof event !== "string" || !event || typeof handler !== "function") {
      throw failure("invalidParams", "An event name and handler function are required.");
    }
    let handlers = listeners.get(event);
    if (!handlers) { handlers = new Set(); listeners.set(event, handlers); }
    handlers.add(handler);
    let subscribed = true;
    return function () {
      if (!subscribed) return;
      subscribed = false;
      handlers.delete(handler);
      if (!handlers.size && listeners.get(event) === handlers) listeners.delete(event);
    };
  }

  global.addEventListener("pagehide", function () {
    for (const id of Array.from(pending.keys())) {
      settle(id, failure("disconnected", "The add-on page was closed."));
    }
    connection = null;
  });

  global.MorphbenchAddon = Object.freeze({ connect: connect, request: request, on: on });
})(window);
