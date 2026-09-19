export function openModal(id: string) {
  document.getElementById(`modal-${id}`)?.classList.add('open')
}
