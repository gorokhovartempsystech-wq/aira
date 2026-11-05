"use strict";

// No installers have been released. Keep download actions informational until
// real, verified release artifacts and their platform requirements are available.
const dialog = document.querySelector(".info-dialog");
const title = document.querySelector("#dialog-title");
const description = document.querySelector("#dialog-description");
const eyebrow = document.querySelector("#dialog-eyebrow");
const details = document.querySelector("#dialog-details");

const messages = {
  windows: {
    eyebrow: "Первый релиз · Windows",
    title: "Скоро на вашем компьютере.",
    description: "Мы готовим AIRA для Windows. Как только первый релиз будет готов, здесь появится установщик.",
    details: ["Версия, размер файла и поддерживаемые версии Windows будут указаны перед скачиванием.", "Для активации понадобится ключ лицензии. Одна лицензия — одно устройство."],
  },
  macos: {
    eyebrow: "Первый релиз · macOS",
    title: "Скоро на вашем Mac.",
    description: "Мы готовим AIRA для macOS. Как только первый релиз будет готов, здесь появится установщик.",
    details: ["Версия, размер файла, поддерживаемые процессоры и версии macOS будут указаны перед скачиванием.", "Для активации понадобится ключ лицензии. Одна лицензия — одно устройство."],
  },
  about: {
    eyebrow: "Знакомьтесь, AIRA",
    title: "От идеи к ясному требованию.",
    description: "Мы создаём настольный редактор, который помогает находить неоднозначности в требованиях. Вы запускаете проверку, разбираете замечания и сами решаете, что изменить.",
    details: ["В первом релизе планируем работу с DOCX и проверку локальной моделью, которая будет входить в установщик.", "Приложение находится в разработке. Скачивание откроется после подготовки первого релиза."],
  },
  requirements: {
    eyebrow: "Перед установкой",
    title: "Несколько важных деталей.",
    description: "AIRA готовится к выпуску для Windows и macOS. Точные системные требования опубликуем вместе с установщиками.",
    details: ["Модель будет входить в установщик. Требования к памяти и свободному месту пока уточняются.", "Для активации нужен ключ лицензии. Интернет необходим при каждом запуске для проверки лицензии; анализ документов выполняется локально."],
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

document.querySelectorAll("[data-dialog], [data-platform]").forEach((button) => {
  button.addEventListener("click", () => showInfo(button.dataset.dialog || button.dataset.platform));
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
