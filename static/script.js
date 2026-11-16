
console.log("CityFix application loaded successfully!");

document.querySelectorAll("form").forEach(function(form) {
    form.addEventListener("submit", function() {
        console.log("Form submitted successfully.");
    });
});
