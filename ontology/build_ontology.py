"""Build the PV simulation pipeline ontology with Owlready2.

Run:  python build_ontology.py
Output: pv_pipeline.owl (RDF/XML, opens in Protege or WebProtege)

This script is separate from the PV-DIAL app. The app does not import it.

The stage-to-model mapping below is written by the researcher. pvlib does not
label its functions by stage. The lists follow the PV-DIAL model pool checked
against pvlib 0.15.2 (methodology.md, activity A6) and the adapter code.
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

# Stage id, display name, then the selectable models.
# Each model: (PV-DIAL model name, pvlib functions, condition or None).
STAGES = [
    (
        "Decomposition",
        "Decomposition",
        [
            ("erbs", ["pvlib.irradiance.erbs"], None),
            ("erbs_driesse", ["pvlib.irradiance.erbs_driesse"], None),
            ("disc", ["pvlib.irradiance.disc"], None),
            ("dirint", ["pvlib.irradiance.dirint"], None),
            ("boland", ["pvlib.irradiance.boland"], None),
            ("louche", ["pvlib.irradiance.louche"], None),
            ("orgill_hollands", ["pvlib.irradiance.orgill_hollands"], None),
        ],
    ),
    (
        "Transposition",
        "Transposition",
        [
            ("isotropic", ["pvlib.irradiance.isotropic"], None),
            ("klucher", ["pvlib.irradiance.klucher"], None),
            ("haydavies", ["pvlib.irradiance.haydavies"], None),
            ("reindl", ["pvlib.irradiance.reindl"], None),
            ("king", ["pvlib.irradiance.king"], None),
            ("perez", ["pvlib.irradiance.perez"], None),
            ("perez-driesse", ["pvlib.irradiance.perez_driesse"], None),
        ],
    ),
    (
        "CellTemperature",
        "Cell temperature",
        [
            ("faiman", ["pvlib.temperature.faiman"], None),
            ("pvsyst_cell", ["pvlib.temperature.pvsyst_cell"], None),
            (
                "sapm_cell",
                ["pvlib.temperature.sapm_cell"],
                "Selectable only where the mounting combination has SAPM coefficients.",
            ),
            (
                "fuentes",
                ["pvlib.temperature.fuentes"],
                "Selectable only when the module has a NOCT value (CEC module library). "
                "Also needs the module height entered by the user.",
            ),
            (
                "noct_sam",
                ["pvlib.temperature.noct_sam"],
                "Selectable only when the module has a NOCT value (CEC module library).",
            ),
            (
                "ross",
                ["pvlib.temperature.ross"],
                "Selectable only when the module has a NOCT value (CEC module library).",
            ),
        ],
    ),
    (
        "DCPower",
        "DC power",
        [
            (
                "pvwatts_dc",
                ["pvlib.pvsystem.pvwatts_dc"],
                "Produces no DC voltage, so it cannot be paired with the sandia or adr inverter models.",
            ),
            (
                "sapm",
                ["pvlib.pvsystem.sapm_effective_irradiance", "pvlib.pvsystem.sapm"],
                "Selectable only for modules in the Sandia module library.",
            ),
            (
                "singlediode_desoto",
                ["pvlib.pvsystem.calcparams_desoto", "pvlib.pvsystem.singlediode"],
                "Selectable only for modules in the CEC module library.",
            ),
            (
                "singlediode_cec",
                ["pvlib.pvsystem.calcparams_cec", "pvlib.pvsystem.singlediode"],
                "Selectable only for modules in the CEC module library.",
            ),
        ],
    ),
    (
        "ACConversion",
        "AC conversion",
        [
            (
                "sandia",
                ["pvlib.inverter.sandia"],
                "Needs DC voltage from the DC power stage and an inverter in the CEC inverter library.",
            ),
            (
                "adr",
                ["pvlib.inverter.adr"],
                "Needs DC voltage from the DC power stage and an inverter in the ADR inverter library.",
            ),
            ("pvwatts", ["pvlib.inverter.pvwatts"], None),
        ],
    ),
]

# Notes about how a whole stage is run.
STAGE_NOTES = {
    "Transposition": (
        "The adapter calls pvlib.irradiance.get_total_irradiance(model=...), "
        "which runs the listed function for the chosen model."
    ),
}

with onto:
    # ---- Classes (the kinds of things in the domain) ----
    class Pipeline(Thing):
        """A full PV simulation run made of ordered stages."""

    class Stage(Thing):
        """One step of the pipeline, for example decomposition."""

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

    class pvlibFunction(DataProperty):
        """A pvlib function that implements the model. A model can use more than one."""
        domain = [Model]
        range = [str]

    # ---- Individuals (the actual stages and models) ----
    pipeline = Pipeline("PVSimulationPipeline")
    previous = None

    for order, (stage_id, stage_label, models) in enumerate(STAGES, start=1):
        stage = Stage(stage_id)
        stage.label = [stage_label]
        stage.stageOrder = order
        if stage_id in STAGE_NOTES:
            stage.comment = [STAGE_NOTES[stage_id]]
        pipeline.hasStage.append(stage)

        if previous is not None:
            previous.precedes.append(stage)
        previous = stage

        for model_name, functions, condition in models:
            model = Model(model_name)
            model.pvlibFunction = functions
            if condition:
                model.comment = [condition]
            stage.hasCandidateModel.append(model)

onto.save(file="pv_pipeline.owl", format="rdfxml")

# Short summary so you can see what was built.
print("Saved pv_pipeline.owl")
print("Classes:   ", [c.name for c in onto.classes()])
print("Properties:", [p.name for p in onto.properties()])
for stage in sorted(onto.Stage.instances(), key=lambda s: s.stageOrder):
    names = [m.name for m in stage.hasCandidateModel]
    print(f"  {stage.stageOrder}. {stage.label[0]} ({len(names)}): {names}")
print("Models in total:", len(onto.Model.instances()))
