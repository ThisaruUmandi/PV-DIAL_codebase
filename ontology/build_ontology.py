"""Build a small PV simulation pipeline ontology with Owlready2.

Run:  python build_ontology.py
Output: pv_pipeline.owl (RDF/XML, opens in Protege or WebProtege)

This script is separate from the PV-DIAL app. The app does not import it.
"""

from owlready2 import (
    DataProperty,
    FunctionalProperty,
    ObjectProperty,
    Thing,
    get_ontology,
)

# The IRI is only a unique name for the ontology. It does not need to be a real web page.
onto = get_ontology("http://example.org/pv-pipeline.owl")

with onto:
    # ---- Classes (the kinds of things in the domain) ----
    class Pipeline(Thing):
        """A full PV simulation run made of ordered stages."""

    class Stage(Thing):
        """One step of the pipeline, for example irradiance decomposition."""

    class Model(Thing):
        """A method that can be chosen to carry out a stage."""

    class Parameter(Thing):
        """An input value that a model needs."""

    # ---- Object properties (links between things) ----
    class hasStage(ObjectProperty):
        domain = [Pipeline]
        range = [Stage]

    class precedes(ObjectProperty):
        """Stage order: this stage runs before the other one."""
        domain = [Stage]
        range = [Stage]

    class hasCandidateModel(ObjectProperty):
        domain = [Stage]
        range = [Model]

    class hasParameter(ObjectProperty):
        domain = [Model]
        range = [Parameter]

    # ---- Data properties (plain values) ----
    class stageOrder(DataProperty, FunctionalProperty):
        domain = [Stage]
        range = [int]

    class pvlibFunction(DataProperty, FunctionalProperty):
        """Name of the pvlib function that implements the model."""
        domain = [Model]
        range = [str]

    # ---- Individuals (the actual stages and models) ----
    # Stage name -> list of (model name, pvlib function).
    # EXAMPLES ONLY: replace the model lists with the ones PV-DIAL really uses.
    stages = {
        "IrradianceDecomposition": [
            ("Erbs", "pvlib.irradiance.erbs"),
            ("DISC", "pvlib.irradiance.disc"),
            ("DIRINT", "pvlib.irradiance.dirint"),
        ],
        "POATransposition": [
            ("Isotropic", "pvlib.irradiance.isotropic"),
            ("HayDavies", "pvlib.irradiance.haydavies"),
            ("Perez", "pvlib.irradiance.perez"),
        ],
        "CellTemperature": [
            ("SAPMCell", "pvlib.temperature.sapm_cell"),
            ("Faiman", "pvlib.temperature.faiman"),
        ],
        "DCPower": [
            ("SingleDiode", "pvlib.pvsystem.singlediode"),
            ("PVWattsDC", "pvlib.pvsystem.pvwatts_dc"),
        ],
        "ACConversion": [
            ("SandiaInverter", "pvlib.inverter.sandia"),
            ("PVWattsInverter", "pvlib.inverter.pvwatts"),
        ],
    }

    pipeline = Pipeline("PVSimulationPipeline")
    previous = None

    for order, (stage_name, models) in enumerate(stages.items(), start=1):
        stage = Stage(stage_name)
        stage.stageOrder = order
        pipeline.hasStage.append(stage)

        if previous is not None:
            previous.precedes.append(stage)
        previous = stage

        for model_name, function_name in models:
            model = Model(model_name)
            model.pvlibFunction = function_name
            stage.hasCandidateModel.append(model)

onto.save(file="pv_pipeline.owl", format="rdfxml")

# Short summary so you can see what was built.
print("Saved pv_pipeline.owl")
print("Classes:   ", [c.name for c in onto.classes()])
print("Properties:", [p.name for p in onto.properties()])
for stage in sorted(onto.Stage.instances(), key=lambda s: s.stageOrder):
    names = [m.name for m in stage.hasCandidateModel]
    print(f"  {stage.stageOrder}. {stage.name}: {names}")