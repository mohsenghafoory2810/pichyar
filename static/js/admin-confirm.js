// Order page (admin): ask before submitting a form that has data-confirm="question".
document.addEventListener("submit", function (event) {
  var question = event.target.getAttribute && event.target.getAttribute("data-confirm");
  if (question && !window.confirm(question)) event.preventDefault();
});
