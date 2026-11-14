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
  macInstall: {
    eyebrow: "Пилотная версия для Mac",
    title: "Как открыть AIRA.",
    description: "Эта сборка пока не подписана сертификатом разработчика и не прошла проверку Apple. Поэтому macOS может заблокировать первое открытие.",
    details: ["Скачивайте установщик с этого сайта. Модель проверяет требования локально на вашем компьютере."],
    steps: [
      "Откройте скачанный DMG и перенесите AIRA в папку «Программы».",
      "Запустите AIRA из «Программ». Если появится предупреждение Apple, нажмите «Готово».",
      "Откройте  → «Системные настройки» → «Конфиденциальность и безопасность».",
      "Прокрутите до раздела «Безопасность». Рядом с сообщением об AIRA нажмите «Всё равно открыть».",
      "Подтвердите запуск паролем Mac или Touch ID и нажмите «Открыть».",
    ],
    afterSteps: "Если кнопки нет, снова запустите AIRA и вернитесь в настройки. Разрешайте запуск только для сборки, которую вы скачали с нашего сайта и решили использовать.",
    helpUrl: "https://support.apple.com/ru-ru/102445",
  },
  requirements: {
    eyebrow: "Перед установкой",
    title: "Системные требования.",
    description: "Windows 10/11, 64 бита (x64), или macOS 14 и новее на Mac с чипом Apple Silicon (M1 и новее).",
    details: [
      "В установщик включены редактор AIRA и локальная модель. Требования проверяются на вашем компьютере.",
      "Вместе с AIRA устанавливаются Python и библиотеки для запуска редактора и модели, а также PostgreSQL для хранения документов, черновиков и результатов. Устанавливать их отдельно не требуется.",
      "Пакет также содержит компонент обновлений: Sparkle на Mac и WinSparkle на Windows. Для окна Windows-приложения нужен Microsoft Edge WebView2 Runtime.",
      "Папка программы выбирается в Windows-установщике; данные пользователя хранятся отдельно от неё. На первом запуске AIRA подготавливает хранилище и проверяет целостность файлов модели.",
      "У пилотного Windows-установщика пока нет подписи издателя: SmartScreen может показать предупреждение о неизвестном приложении.",
      "На Mac откройте скачанный образ и перенесите AIRA в «Программы». Если AIRA уже установлена, закройте её перед заменой.",
      "Ключ вводится один раз, при активации. При следующих запусках лицензия проверяется автоматически через интернет; повторно вводить действующий ключ не нужно.",
      "Сборки Mac проверяют обновления и загружает их автоматически. Установка завершается после сохранения правок и закрытия AIRA. Версии 0.2.4 и ниже нужно один раз заменить вручную из-за переезда сервера.",
      "Сборки Windows проверяют обновления при запуске и предлагает установить новую версию. С версии 0.2.0 нужно один раз обновиться вручную.",
      "После обновления до 0.2.7 нужно один раз повторно ввести ключ активации. Следующие запуски — автоматически, с проверкой лицензии через интернет.",
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
  if (message.steps) {
    const list = document.createElement("ol");
    list.className = "install-steps";
    list.replaceChildren(...message.steps.map((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      return item;
    }));
    details.append(list);
  }
  if (message.afterSteps) {
    const note = document.createElement("p");
    note.textContent = message.afterSteps;
    details.append(note);
  }
  if (message.helpUrl) {
    const paragraph = document.createElement("p");
    const link = document.createElement("a");
    link.href = message.helpUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Официальная инструкция Apple";
    paragraph.append(link);
    details.append(paragraph);
  }
  dialog.showModal();
}

document.querySelectorAll("[data-dialog]").forEach((button) => {
  button.addEventListener("click", () => showInfo(button.dataset.dialog));
});
// Keep the installer link native: show help without cancelling the download.
document.querySelector(".mac-button").addEventListener("click", (event) => {
  if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) showInfo("macInstall");
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


// Published installers are independent of the HTML deployment.
function planReleaseLinks(data) {
  if (!data || data.schema !== 1 || !data.platforms) throw new Error("Invalid release metadata");
  return ["windows-x64", "macos-arm64"].map((platform) => {
    const record = data.platforms[platform];
    if (!record || !/^[0-9]+\.[0-9]+\.[0-9]+$/.test(record.version)
        || !Number.isSafeInteger(record.bytes) || record.bytes < 1 || record.bytes > 2 * 1024 ** 3
        || !/^[0-9a-f]{64}$/.test(record.sha256)) throw new Error("Invalid installer metadata");
    const windows = platform === "windows-x64";
    const filename = windows ? `AIRA-Setup-${record.version}.exe` : `AIRA-${record.version}-apple-silicon.dmg`;
    const url = "https://51.250.81.70/downloads/" + filename;
    if (record.filename !== filename || record.url !== url) throw new Error("Unexpected installer URL");
    return {
      button: windows ? ".windows-button" : ".mac-button",
      note: windows ? "#release-note" : "#mac-release-note",
      url,
      text: `${windows ? "Windows 10/11 (64 бита)" : "macOS 14+ · Apple Silicon"} · ${record.version} · ${Math.ceil(record.bytes / 1000000)} МБ`,
    };
  });
}

async function refreshReleasedVersions() {
  const response = await fetch("https://51.250.81.70/updates/releases.json", {
    cache: "no-store", signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) return;
  const planned = planReleaseLinks(await response.json());
  for (const item of planned) {
    const button = document.querySelector(item.button);
    const note = document.querySelector(item.note);
    if (!button || !note) continue;
    button.href = item.url;
    const dot = note.querySelector(".status-dot");
    note.replaceChildren(...(dot ? [dot] : []), document.createTextNode(item.text));
  }
}
refreshReleasedVersions().catch(() => {});
