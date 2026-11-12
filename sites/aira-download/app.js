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
    details: ["Модель и редактор DOCX уже включены в установщик.", "Проверка требований выполняется на вашем компьютере."],
  },
  requirements: {
    eyebrow: "Перед установкой",
    title: "Системные требования.",
    description: "Windows 10/11, 64 бита (x64), или macOS 14 и новее на Mac с чипом Apple Silicon (M1 и новее).",
    details: [
      "Модель включена в установщик и проверяет требования локально. Отдельно устанавливать Python и базу данных не нужно.",
      "На Mac откройте скачанный образ и перенесите AIRA в «Программы». Если AIRA уже установлена, закройте её перед заменой.",
      "На Mac ключ вводится один раз, при активации. При следующих запусках лицензия проверяется автоматически через интернет; повторно вводить действующий ключ не нужно.",
      "Mac 0.2.6 проверяет обновления и загружает их автоматически. Установка завершается после сохранения правок и закрытия AIRA. Версии 0.2.4 и ниже нужно один раз заменить вручную из-за переезда сервера.",
      "Windows 0.2.0 пока обновляется вручную; активация по ключу в этой сборке ещё не подключена.",
      "У Mac-сборки пока нет подписи Developer ID и проверки Apple, поэтому macOS может заблокировать первое открытие. Это ограничение текущей сборки; автоматическое обновление его не устраняет.",
      "Сборки для Intel Mac и Windows ARM не опубликованы. Минимальный объём оперативной памяти пока не установлен испытаниями.",
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

