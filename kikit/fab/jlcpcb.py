import click
import time
from pcbnewTransition import pcbnew
import csv
import os
import sys
import shutil
from pathlib import Path
import kikit.defs
from kikit.fab.common import *
from kikit.common import *
from kikit.export import gerberImpl

def collectBom(components, lscsFields, ignore, skip_missing, variant):
    bom = {}
    for c in components:
        if getUnit(c) != 1:
            continue
        reference = getReference(c)
        if reference.startswith("#PWR") or reference.startswith("#FL"):
            continue
        if reference in ignore:
            continue
        if getField(c, "JLCPCB_IGNORE") is not None and getField(c, "JLCPCB_IGNORE") != "":
            continue
        if skip_missing and (getField(c, "LCSC") is None or getField(c, "LCSC") == ""):
            continue
        if hasattr(c, "in_bom") and not c.in_bom:
            continue
        if hasattr(c, "on_board") and not c.on_board:
            continue
        if hasattr(c, "dnp") and c.dnp:
            continue
        if getField(c, "KIKIT_VARIANT_DNP") is not None:
            dnp_variants = getField(c, "KIKIT_VARIANT_DNP").split(",")
            if variant in dnp_variants:
                continue
        orderCode = None
        for fieldName in lscsFields:
            orderCode = getField(c, fieldName)
            if orderCode is not None and orderCode.strip() != "":
                break
        cType = (
            getField(c, "Value"),
            getField(c, "Footprint"),
            orderCode
        )
        bom[cType] = bom.get(cType, []) + [reference]
    return bom

def sanitizeFootprintName(footprint: str) -> str:
    # For reasons unknown, JLC seems to not properly assign a component
    # if the footprint contains certain keywords...
    return footprint.replace("foot", "hand")  # foot fetish removal

def sanitizeArchiveName(name: str) -> str:
    replacement_table = {
        "eval": "evl",
        "copy": "cp",
        "convert": "cvt",
        "confirm": "cfm",
        "Copy": "cp",
    }
    while True:
        for old, new in replacement_table.items():
            if old in name:
                name = name.replace(old, new)
        else:
            break
    return name

def bomToCsv(bomData, filename):
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Comment", "Designator", "Footprint", "LCSC"])
        for cType, references in bomData.items():
            # JLCPCB allows at most 200 components per line so we have to split
            # the BOM into multiple lines. Let's make the chunks by 100 just to
            # be sure.
            CHUNK_SIZE = 100
            sortedReferences = sorted(references, key=naturalComponentKey)
            for i in range(0, len(references), CHUNK_SIZE):
                refChunk = sortedReferences[i:i+CHUNK_SIZE]
                value, footprint, lcsc = cType
                footprint = sanitizeFootprintName(footprint)
                writer.writerow([value, ",".join(refChunk), footprint, lcsc])

def dumpUnassignedTable(bomData, filename):
    with open(filename, "w") as fout:
        for cType, references in bomData.items():
            value, footprint, _ = cType
            ref_string = ",".join(references)
            # Print into a left-aligned table
            fout.write(f"{value:<40} {footprint:<60} {ref_string}\n")

def exportJlcpcb(board, outputdir, assembly, gerbers, schematic, ignore, field,
           corrections, correctionpatterns, missingerror, nametemplate, drc,
           remove_footprint, autoname, skip_missing, variant):
    """
    Prepare fabrication files for JLCPCB including their assembly service
    """

    refsToIgnore = parseReferences(ignore)
    Path(outputdir).mkdir(parents=True, exist_ok=True)

    ensureValidBoard(board)
    loadedBoard = pcbnew.LoadBoard(board)

    if gerbers:
        refillAllZones(loadedBoard)
        ensurePassingDrc(loadedBoard)

        removeComponents(loadedBoard, refsToIgnore)

        # Remove specified footprints before generating outputs
        if remove_footprint:
            footprints_to_remove = []
            for fp in loadedBoard.GetFootprints():
                # Use GetLibItemName() for the footprint name within the library
                fp_id_str = f"{fp.GetFPID().GetLibNickname().wx_str()}:{fp.GetFPID().GetLibItemName().wx_str()}"
                if fp_id_str in remove_footprint:
                    footprints_to_remove.append(fp)
            for fp in footprints_to_remove:
                loadedBoard.Delete(fp)

        gerberdir = os.path.join(outputdir, "gerber")
        shutil.rmtree(gerberdir, ignore_errors=True)

        if autoname:
            boardName = os.path.basename(board.replace(".kicad_pcb", ""))
            archiveName = expandNameTemplate(nametemplate, boardName + "-gerbers", loadedBoard)
        else:
            archiveName = expandNameTemplate(nametemplate, "gerbers", loadedBoard)
        archiveName = sanitizeArchiveName(archiveName)

        shutil.make_archive(os.path.join(outputdir, archiveName), "zip", outputdir, "gerber")

        archivePath = os.path.join(outputdir, archiveName)
        archivePathFull = archivePath + ".zip"

        # Delete the archive if it already exists
        Path(archivePathFull).unlink(missing_ok=True)
        gerberImpl(board, gerberdir, board=loadedBoard)

        # Check if there is a file called jlcpcb.json
        jlcpcbConfig = os.path.join(os.path.dirname(board), "jlcpcb.json")
        if os.path.exists(jlcpcbConfig):
            # Copy the file to the output directory
            shutil.copy(jlcpcbConfig, gerberdir)

        shutil.make_archive(archivePath, "zip", outputdir, "gerber")

        ctimeStr = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getctime(archivePathFull)))
        print(f"Gerber files archived in {archivePathFull} (creation time {ctimeStr})")

    if not assembly:
        return
    if schematic is None:
        schematic = str(Path(board).with_suffix(".kicad_sch"))

    ensureValidSch(schematic)

    correctionFields = [x.strip() for x in corrections.split(",")]
    components = extractComponents(schematic)
    ordercodeFields = [x.strip() for x in field.split(",")]
    bom = collectBom(
        components, ordercodeFields,
        refsToIgnore, skip_missing, variant
    )

    bom_refs = set(x for xs in bom.values() for x in xs)
    bom_components = [c for c in components if getReference(c) in bom_refs]

    posData = collectPosData(loadedBoard, correctionFields,
        bom=bom_components, posFilter=noFilter, correctionFile=correctionpatterns,
        orientationHandling=FootprintOrientationHandling.MirrorBottom)
    boardReferences = set([x[0] for x in posData])
    bom = {key: [v for v in val if v in boardReferences] for key, val in bom.items()}
    bom = {key: val for key, val in bom.items() if len(val) > 0}


    missingFields = False
    for type, references in bom.items():
        _, _, lcsc = type
        if not lcsc:
            missingFields = True
            for r in references:
                print(f"WARNING: Component {r} is missing ordercode")
    if missingFields and missingerror:
        sys.exit("There are components with missing ordercode, aborting")

    bom_with_missing = collectBom(
        components, ordercodeFields,
        refsToIgnore, False, variant
    )
    bom_missing = {key: val for key, val in bom_with_missing.items() if not key[-1]}

    dumpUnassignedTable(bom_missing, os.path.join(outputdir, expandNameTemplate(nametemplate, "unassigned", loadedBoard)) + ".txt")
    posDataToFile(posData, os.path.join(outputdir, expandNameTemplate(nametemplate, "pos", loadedBoard) + ".csv"))
    bomToCsv(bom, os.path.join(outputdir, expandNameTemplate(nametemplate, "bom", loadedBoard) + ".csv"))

    # Look for QR code squares on silkscreen layers
    dumpQRSquares(loadedBoard)

def dumpQRSquares(loadedBoard):
    """
    Find filled rectangles on silkscreen layers that are 5x5, 8x8, or 10x10 mm
    and print their location and size information for QR code placement.
    """
    target_sizes = [5.0, 8.0, 10.0]  # mm
    tolerance = 0.1  # mm tolerance for size matching

    # Find silkscreen layers by name (more robust than hardcoded layer IDs)
    silkscreen_layers = []
    all_drawings = list(loadedBoard.GetDrawings())

    # Get all unique layers
    all_layers = set(drawing.GetLayer() for drawing in all_drawings)

    # Find layers with "Silk" in their name
    for layer_id in all_layers:
        try:
            layer_name = loadedBoard.GetLayerName(layer_id)
            if "silk" in layer_name.lower() or "silkscreen" in layer_name.lower():
                silkscreen_layers.append((layer_id, layer_name))
        except:
            continue

    if not silkscreen_layers:
        return  # No silkscreen layers found

    qr_squares_found = 0

    for drawing in all_drawings:
        layer = drawing.GetLayer()

        # Check if this drawing is on a silkscreen layer
        if not any(layer == sl[0] for sl in silkscreen_layers):
            continue

        # Only process PCB_SHAPE objects (geometric shapes)
        if type(drawing).__name__ != "PCB_SHAPE":
            continue

        # Check if it's a rectangle
        shape = drawing.GetShape()
        if shape != kikit.defs.STROKE_T.S_RECT:
            continue

        # Get rectangle corners and calculate dimensions
        corners = drawing.GetRectCorners()
        if len(corners) < 4:
            continue

        # Calculate width and height
        width_mm = toMm(abs(corners[2].x - corners[0].x))
        height_mm = toMm(abs(corners[2].y - corners[0].y))

        # Check if it matches target sizes (with tolerance)
        size_match = any(abs(width_mm - size) < tolerance and abs(height_mm - size) < tolerance
                         for size in target_sizes)

        if size_match:
            qr_squares_found += 1
            # Calculate center position
            center_x = toMm((corners[0].x + corners[2].x) / 2)
            center_y = toMm((corners[0].y + corners[2].y) / 2)

            # Find layer name
            layer_name = "Unknown"
            for layer_id, name in silkscreen_layers:
                if layer == layer_id:
                    layer_name = name
                    break

            print(f"QR Square found: {width_mm:.1f}x{height_mm:.1f}mm on {layer_name} at ({center_x:.2f}, {center_y:.2f})mm")
