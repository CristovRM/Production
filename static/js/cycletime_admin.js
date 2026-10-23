document.addEventListener('DOMContentLoaded', function () {
    const processSelect = document.getElementById('id_process_type');
    const machineSelect = document.getElementById('id_machine_type');

    processSelect.addEventListener('change', function () {
        const processId = this.value;
        fetch(`/ajax/get-machines/?process_type=${processId}`)
            .then(response => response.json())
            .then(data => {
                machineSelect.innerHTML = '';
                data.forEach(machine => {
                    const option = document.createElement('option');
                    option.value = machine.id;
                    option.textContent = machine.name;
                    machineSelect.appendChild(option);
                });
            });
    });
});
