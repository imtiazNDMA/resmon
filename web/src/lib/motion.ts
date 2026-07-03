import gsap from "gsap";

/** App load: sidebar slides in, buttons stagger, stage fades from black. */
export function appLoadIn(root: HTMLElement) {
  const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
  tl.from(root.querySelector(".sidebar"), { x: -40, opacity: 0, duration: 0.5 })
    .from(root.querySelectorAll(".rbtn, .dbtn"), { y: 14, opacity: 0, stagger: 0.08 }, "-=0.2")
    .from(root.querySelector(".stage"), { opacity: 0, duration: 0.9 }, "-=0.3");
  return tl;
}

/** View swap: incoming view fades/settles from a slight scale offset. */
export function viewSwap(stage: HTMLElement, entering: "map" | "dashboard") {
  const tl = gsap.timeline({ defaults: { ease: "power2.inOut" } });
  tl.fromTo(
    stage,
    { opacity: 0.25, scale: entering === "dashboard" ? 1.02 : 0.98 },
    { opacity: 1, scale: 1, duration: 0.45 },
  );
  return tl;
}

/** Numbers count, never snap. */
export function countTo(el: HTMLElement, value: number, decimals = 1) {
  const obj = { v: parseFloat(el.textContent ?? "0") || 0 };
  return gsap.to(obj, {
    v: value,
    duration: 0.8,
    ease: "power1.out",
    onUpdate: () => {
      el.textContent = obj.v.toFixed(decimals);
    },
  });
}

/** Vertical meter eases to a 0..1 fraction. */
export function meterTo(fillEl: HTMLElement, fraction: number) {
  return gsap.to(fillEl, {
    height: `${Math.max(0, Math.min(1, fraction)) * 100}%`,
    duration: 0.7,
    ease: "power2.out",
  });
}

/** Timeline dock rises from the bottom edge. */
export function dockRise(el: HTMLElement) {
  return gsap.from(el, { yPercent: 110, duration: 0.55, ease: "power3.out" });
}

/** Dashboard panels stagger in with a 60ms cascade (spec motion score). */
export function panelsIn(root: HTMLElement) {
  return gsap.from(root.querySelectorAll(".panel"), {
    y: 18,
    opacity: 0,
    stagger: 0.06,
    duration: 0.45,
    ease: "power3.out",
  });
}

/** Highlight sweep across a clicked reservoir button. */
export function buttonSweep(el: HTMLElement) {
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  el.appendChild(sweep);
  return gsap.fromTo(
    sweep,
    { xPercent: -110 },
    {
      xPercent: 110,
      duration: 0.6,
      ease: "power2.out",
      onComplete: () => sweep.remove(),
    },
  );
}
