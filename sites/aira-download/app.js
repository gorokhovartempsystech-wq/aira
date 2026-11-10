"use strict";

const dialog = document.querySelector(".info-dialog");
const title = document.querySelector("#dialog-title");
const description = document.querySelector("#dialog-description");
const eyebrow = document.querySelector("#dialog-eyebrow");
const details = document.querySelector("#dialog-details");

const messages = {
  about: {
    eyebrow: "Знакомьтесь, AIRA",
    title: "От идеи к ясному требованию.",
    description: "Мы создаём настольный редактор, который помогает находить неоднозначности в требованиях. Вы запускаете проверку, разбираете замечания и сами решаете, что изменить.",
    details: ["Пилоты Windows и macOS включают локальную модель и редактор DOCX.", "При первом запуске AIRA на Mac введите выданный ключ активации. Адрес сервера уже встроен."],
  },
  requirements: {
    eyebrow: "Перед установкой",
    title: "Несколько важных деталей.",
    description: "Пилот Windows работает на Windows 10/11 x64. Пилот macOS предназначен для Mac с Apple Silicon.",
    details: [
      "Обе сборки скачиваются с сервера AIRA, вход в GitHub не нужен. Windows 0.2.0 — пилот без лицензирования и автообновления.",
      "На Mac откройте скачанный образ и перенесите AIRA в «Программы». Если AIRA уже установлена, закройте её перед заменой.",
      "На Mac при первом запуске введите выданный ключ. Для активации и последующих запусков нужен интернет.",
      "Mac 0.2.5 проверяет обновления и загружает их автоматически. Установка завершается после сохранения правок и закрытия AIRA. Версии 0.2.4 и ниже нужно один раз заменить вручную из-за переезда сервера.",
      "Сборки пока без подписи издателя Apple/Microsoft. Версии для Intel Mac и Windows ARM не опубликованы.",
    ],
  },
};

function showInfo(key) {
  const message = messages[key];
  if (!message) return;
  eyebrow.textContent = message.eyebrow;
  title.textContent = message.title;
  description.textContent = message.description;
  details.replaceChildren(...message.details.map((text) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    return paragraph;
  }));
  dialog.showModal();
}

document.querySelectorAll("[data-dialog]").forEach((button) => {
  button.addEventListener("click", () => showInfo(button.dataset.dialog));
});
document.querySelector(".dialog-close").addEventListener("click", () => dialog.close());
document.querySelector(".dialog-done").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  const bounds = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
});

// A quiet field of contours: generated locally, no image/font/CDN requests.
const contourLines = document.querySelector("#contour-lines");
for (let ring = 0; ring < 28; ring += 1) {
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  const radius = 96 + ring * 7.1;
  const points = [];
  for (let step = 0; step <= 120; step += 1) {
    const angle = (step / 120) * Math.PI * 2;
    const wave = Math.sin(angle * 3 + ring * .075) * (12 + ring * .28);
    const x = 450 + Math.cos(angle) * (radius + wave) * 1.27;
    const y = 255 + Math.sin(angle) * (radius + wave) * .58;
    points.push(`${step === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`);
  }
  path.setAttribute("d", `${points.join(" ")} Z`);
  contourLines.append(path);
}

const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const finePointer = window.matchMedia("(pointer: fine)");
const artwork = document.querySelector(".hero-art");
document.addEventListener("pointermove", (event) => {
  if (motionPreference.matches || !finePointer.matches) return;
  artwork.style.setProperty("--pointer-x", `${(event.clientX / window.innerWidth - .5) * 32}px`);
  artwork.style.setProperty("--pointer-y", `${(event.clientY / window.innerHeight - .5) * 20}px`);
}, { passive: true });
document.documentElement.addEventListener("pointerleave", () => {
  artwork.style.setProperty("--pointer-x", "0px");
  artwork.style.setProperty("--pointer-y", "0px");
});
