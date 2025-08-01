function speakText() {
    let text = document.getElementById('textoSimplificado').innerText;
    let speech = new SpeechSynthesisUtterance(text);
    speech.lang = "pt-BR";

    speech.onstart = function(){
        window.postMessage({type:'avatar.talk', start:true});
    };
    speech.onend = function(){
        window.postMessage({type:'avatar.talk', start:false});
    };

    window.speechSynthesis.speak(speech);
}

let dropArea = document.getElementById('drop-area');
let fileInput = document.getElementById('fileElem');

dropArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropArea.classList.add('hover');
});
dropArea.addEventListener('dragleave', () => dropArea.classList.remove('hover'));
dropArea.addEventListener('drop', (e) => {
    e.preventDefault();
    dropArea.classList.remove('hover');
    handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => handleFiles(fileInput.files));

function handleFiles(files) {
    if (files.length > 0) {
        uploadFile(files[0]);
    }
}

function uploadFile(file) {
    let formData = new FormData();
    formData.append("file", file);
    fetch("/processar", { method: "POST", body: formData })
        .then(res => res.json())
        .then(data => {
            document.getElementById("textoSimplificado").innerText = data.texto;
            let link = document.getElementById("downloadLink");
            link.href = "/download_pdf";
            link.style.display = "inline-block";
            speakText();
        });
}
