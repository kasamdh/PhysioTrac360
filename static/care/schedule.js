(() => {
  "use strict";

  const calendar = document.querySelector("[data-appointment-calendar]");
  const dialog = document.getElementById("calendar-move-dialog");
  const form = document.getElementById("calendar-move-form");
  const dateInput = document.getElementById("calendar-move-date");
  const status = document.getElementById("calendar-move-status");

  if (!calendar || !dialog || !form || !dateInput || !status) {
    return;
  }

  const csrfToken = form.querySelector("input[name='csrfmiddlewaretoken']")?.value;
  const moveSubmit = form.querySelector("button[type='submit']");
  const dayCells = [...calendar.querySelectorAll("[data-calendar-date]")];
  let draggedEvent = null;
  let isMoving = false;
  let suppressClickUntil = 0;

  const announce = (message) => {
    status.textContent = "";
    window.setTimeout(() => {
      status.textContent = message;
    }, 20);
  };

  const clearDropTargets = () => {
    dayCells.forEach((day) => day.classList.remove("is-drop-target", "is-moving"));
  };

  const setMovingState = (moving) => {
    isMoving = moving;
    if (moveSubmit) {
      moveSubmit.disabled = moving;
    }
    calendar.classList.toggle("is-saving", moving);
  };

  const responsePayload = async (response) => {
    try {
      return await response.json();
    } catch (_) {
      return {};
    }
  };

  const moveAppointment = async (moveUrl, targetDate) => {
    if (!moveUrl || !targetDate || isMoving) {
      return;
    }

    setMovingState(true);
    announce("Moving appointment.");
    try {
      const response = await fetch(moveUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": csrfToken || "",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: new URLSearchParams({ target_date: targetDate }),
      });
      const payload = await responsePayload(response);
      if (!response.ok) {
        throw new Error(payload.detail || "The appointment could not be moved.");
      }
      if (!payload.moved) {
        announce(payload.detail || "This appointment is already on that date.");
        return;
      }

      announce(payload.detail || "Appointment moved.");
      if (dialog.open) {
        dialog.close();
      }
      const fallbackUrl = `${window.location.pathname}?month=${targetDate.slice(0, 7)}&day=${targetDate}`;
      window.location.assign(payload.redirect_url || fallbackUrl);
    } catch (error) {
      announce(error.message || "The appointment could not be moved. Please try again.");
    } finally {
      setMovingState(false);
      clearDropTargets();
    }
  };

  const openMoveDialog = (control) => {
    if (Date.now() < suppressClickUntil || isMoving) {
      return;
    }
    if (typeof dialog.showModal !== "function") {
      announce("Move appointments in a browser that supports the date picker.");
      return;
    }
    dialog.dataset.moveUrl = control.dataset.moveUrl || "";
    dateInput.value = control.dataset.currentDate || "";
    dialog.showModal();
    dateInput.focus();
  };

  calendar.querySelectorAll(".calendar-event-draggable").forEach((eventCard) => {
    eventCard.addEventListener("dragstart", (event) => {
      if (isMoving) {
        event.preventDefault();
        return;
      }
      draggedEvent = eventCard;
      eventCard.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", eventCard.dataset.appointmentId || "");
      announce("Appointment selected. Drop it on a different calendar date to move it.");
    });

    eventCard.addEventListener("dragend", () => {
      eventCard.classList.remove("is-dragging");
      draggedEvent = null;
      suppressClickUntil = Date.now() + 250;
      clearDropTargets();
    });
  });

  dayCells.forEach((dayCell) => {
    dayCell.addEventListener("dragover", (event) => {
      if (!draggedEvent || isMoving) {
        return;
      }
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      if (dayCell.dataset.calendarDate !== draggedEvent.dataset.currentDate) {
        dayCell.classList.add("is-drop-target");
      }
    });

    dayCell.addEventListener("dragleave", (event) => {
      if (!dayCell.contains(event.relatedTarget)) {
        dayCell.classList.remove("is-drop-target");
      }
    });

    dayCell.addEventListener("drop", (event) => {
      if (!draggedEvent || isMoving) {
        return;
      }
      event.preventDefault();
      const moveUrl = draggedEvent.dataset.moveUrl;
      const currentDate = draggedEvent.dataset.currentDate;
      const targetDate = dayCell.dataset.calendarDate;
      if (currentDate === targetDate) {
        announce("This appointment is already scheduled on that date.");
        clearDropTargets();
        return;
      }
      dayCell.classList.add("is-moving");
      moveAppointment(moveUrl, targetDate);
    });
  });

  document.querySelectorAll(".js-appointment-move").forEach((control) => {
    control.addEventListener("click", () => openMoveDialog(control));
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    moveAppointment(dialog.dataset.moveUrl, dateInput.value);
  });

  document.querySelectorAll("[data-calendar-move-cancel]").forEach((control) => {
    control.addEventListener("click", () => dialog.close());
  });
})();
