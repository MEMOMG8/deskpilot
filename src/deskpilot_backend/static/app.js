const talkButton = document.querySelector("#talk-button");
const statusText = document.querySelector("#status-text");
const transcriptionText = document.querySelector("#transcription-text");
const assistantMessage = document.querySelector("#assistant-message");
const actionText = document.querySelector("#action-text");

function setText(element, text, isEmpty = false) {
  element.textContent = text;
  element.classList.toggle("empty", isEmpty);
}

function clearResult() {
  setText(transcriptionText, "No transcription yet.", true);
  setText(assistantMessage, "No response yet.", true);
  setText(actionText, "No action yet.", true);
}

function renderResult(result) {
  const transcription = result.transcription?.text?.trim();
  const assistant = result.assistant;
  const action = assistant?.action;

  setText(
    transcriptionText,
    transcription || "No transcription returned.",
    !transcription,
  );
  setText(
    assistantMessage,
    assistant?.message || "No assistant response returned.",
    !assistant?.message,
  );

  if (action) {
    setText(actionText, `${assistant.status}: ${action.type} ${action.target}`);
  } else {
    setText(actionText, assistant?.status || "No action returned.", !assistant?.status);
  }
}

async function talk() {
  talkButton.disabled = true;
  clearResult();
  setText(statusText, "Listening — speak now");

  let processingTimer = window.setTimeout(() => {
    setText(statusText, "Processing");
  }, 4200);

  try {
    const response = await fetch("/api/v1/microphone/commands", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        duration_seconds: 4,
        speak: true,
      }),
    });

    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(payload.detail || "DeskPilot could not complete the request.");
    }

    renderResult(payload);
    setText(statusText, "Completed");
  } catch (error) {
    setText(statusText, "Error");
    setText(
      assistantMessage,
      error instanceof Error ? error.message : "DeskPilot could not complete the request.",
    );
  } finally {
    window.clearTimeout(processingTimer);
    talkButton.disabled = false;
  }
}

talkButton.addEventListener("click", talk);
