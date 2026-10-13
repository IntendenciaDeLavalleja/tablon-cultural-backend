document.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.drawerToggle) {
    const sidebar = document.getElementById(button.dataset.drawerToggle);
    sidebar?.classList.toggle('-translate-x-full');
    button.setAttribute('aria-expanded', String(!sidebar?.classList.contains('-translate-x-full')));
  }
  if (button.dataset.dismissTarget) document.querySelector(button.dataset.dismissTarget)?.remove();
  const modalId = button.dataset.modalToggle || button.dataset.modalHide;
  if (modalId) {
    const modal = document.getElementById(modalId);
    const opening = Boolean(button.dataset.modalToggle);
    modal?.classList.toggle('hidden', !opening);
    modal?.classList.toggle('flex', opening);
    modal?.classList.toggle('bg-black/50', opening);
    modal?.setAttribute('aria-hidden', String(!opening));
    if (opening) modal?.focus();
  }
  if (button.dataset.logDetails) alert(button.dataset.logDetails);
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    document.querySelectorAll('[data-modal-hide]').forEach(button => button.click());
  }
});
