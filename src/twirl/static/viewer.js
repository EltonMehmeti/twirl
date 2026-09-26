// G3 · dress photo viewer: a photo opens full screen, grown from where it sits; pinch, double-tap,
// click or wheel to zoom, swipe or ← → between photos. PhotoSwipe 5.4.4 (MIT, static/photoswipe/);
// its core loads on the first tap. Without this script the links still open the photo itself.
import PhotoSwipeLightbox from "./photoswipe/photoswipe-lightbox.esm.min.js";

var gallery = document.querySelector("[data-viewer]");
if (gallery) viewer(gallery);

function viewer(gallery) {
  var t = gallery.dataset;
  var canFullscreen = document.fullscreenEnabled || document.webkitFullscreenEnabled;
  var lightbox = new PhotoSwipeLightbox({
    gallery: gallery,
    children: "a",
    pswpModule: function () {
      return import("./photoswipe/photoswipe.esm.min.js").catch(function (error) {
        // Offline, or the file is blocked: show the photo on its own rather than nothing.
        var link = gallery.children[lightbox.options.index];
        if (link) location.assign(link.href);
        throw error;
      });
    },
    mainClass: "v-viewer",
    bgOpacity: 1,
    wheelToZoom: true,
    // Keep the photo clear of the top bar, and of the arrows on a computer.
    paddingFn: function (viewport) {
      var side = viewport.x >= 960 ? 80 : 0;
      return { top: 64, bottom: 16, left: side, right: side };
    },
    // Controls are words, as everywhere on Vesha; the word is the button's name.
    closeTitle: "",
    closeSVG: html(t.close),
    zoomTitle: "",
    zoomSVG: '<span class="v-viewer__in">' + html(t.zoomIn) + '</span><span class="v-viewer__out">' + html(t.zoomOut) + "</span>",
    arrowPrevTitle: t.prev,
    arrowPrevSVG: '<span aria-hidden="true">←</span>',
    arrowNextTitle: t.next,
    arrowNextSVG: '<span aria-hidden="true">→</span>',
    errorMsg: t.error, // set as text, not HTML
  });

  // The phone's Back button closes the viewer instead of leaving the dress.
  var entry = false, restoration = null;

  lightbox.on("beforeOpen", function () {
    // Motion comes from the design tokens. Reduced motion: PhotoSwipe drops the animations; a fade stays.
    var options = lightbox.pswp.options, css = getComputedStyle(document.documentElement);
    var base = parseFloat(css.getPropertyValue("--dur-base")) || 0;
    options.showAnimationDuration = base;
    options.hideAnimationDuration = parseFloat(css.getPropertyValue("--dur-short")) || 0;
    if (options.zoomAnimationDuration) options.zoomAnimationDuration = base;
    options.easing = css.getPropertyValue("--ease-out").trim();
    if (options.showHideAnimationType === "none") options.showHideAnimationType = "fade";

    // Going back to the page must not restore an old scroll position under the closing photo.
    restoration = history.scrollRestoration;
    history.scrollRestoration = "manual";
    history.pushState({ viewer: true }, "");
    entry = true;
  });

  lightbox.on("firstUpdate", function () {
    var root = lightbox.pswp.element;
    root.setAttribute("aria-label", t.label);
    root.setAttribute("aria-modal", "true");
  });

  lightbox.addFilter("uiElement", function (element, data) {
    if (data.name === "counter") element.setAttribute("aria-live", "polite");
    return element;
  });

  // Native full screen hides the browser's bars too. iPhones don't offer it to pages, so no button there.
  lightbox.on("uiRegister", function () {
    if (!canFullscreen) return;
    lightbox.pswp.ui.registerElement({
      name: "fullscreen",
      order: 15,
      isButton: true,
      html: html(t.full),
      onInit: function (button, pswp) {
        function label() { button.textContent = fullscreenElement() ? t.fullExit : t.full; }
        document.addEventListener("fullscreenchange", label);
        document.addEventListener("webkitfullscreenchange", label);
        pswp.on("destroy", function () {
          document.removeEventListener("fullscreenchange", label);
          document.removeEventListener("webkitfullscreenchange", label);
        });
      },
      onClick: function (event, button, pswp) {
        if (fullscreenElement()) exitFullscreen();
        else requestFullscreen(pswp.element);
      },
    });
  });

  lightbox.on("close", function () {
    var pswp = lightbox.pswp, link = gallery.children[pswp.currIndex];
    if (fullscreenElement()) {
      pswp.options.showHideAnimationType = "fade";
      exitFullscreen();
    } else if (link) {
      // Land on the photo you ended on: the phone strip scrolls to it before the photo flies back.
      gallery.scrollLeft += link.getBoundingClientRect().left - gallery.getBoundingClientRect().left;
      var box = link.getBoundingClientRect();
      if (box.bottom < 0 || box.top > innerHeight) pswp.options.showHideAnimationType = "fade";
    }
    if (entry) {
      entry = false;
      history.back();
    }
  });

  addEventListener("popstate", function () {
    if (restoration) {
      history.scrollRestoration = restoration;
      restoration = null;
    }
    if (entry && lightbox.pswp) {
      entry = false;
      lightbox.pswp.close();
    }
  });

  lightbox.init();
}

function html(text) {
  var span = document.createElement("span");
  span.textContent = text || "";
  return span.innerHTML;
}

function fullscreenElement() {
  return document.fullscreenElement || document.webkitFullscreenElement;
}

function requestFullscreen(element) {
  var request = element.requestFullscreen || element.webkitRequestFullscreen;
  var pending = request && request.call(element);
  if (pending && pending.catch) pending.catch(function () {});
}

function exitFullscreen() {
  var exit = document.exitFullscreen || document.webkitExitFullscreen;
  if (exit) exit.call(document);
}
