SIDE = "right";
GRID_SIZE = 19.05;
MX_SOCKET = [["height", 8.2], ["tolerance", -0.11]];
BASE_HEIGHT = 4.2;

THUMB1 = [["position", GridCoords(0, 0, 0)]];
THUMB2 = [["position", GridCoords(1, 0.25, 0)]];
THUMB3 = [["position", GridCoords(2, 0.5, 0)]];
INDEX = [["position", GridCoords(3, 2.25, 0)]];
MIDDLE = [["position", GridCoords(4, 2.5, 0)]];
RING = [["position", GridCoords(5, 2.25, 0)]];
LITTLE = [["position", GridCoords(6, 1.25, 0)]];

SWITCH_PLACEMENT = [
    THUMB1,
    THUMB2,
    THUMB3,
    INDEX,
    MIDDLE,
    RING,
    LITTLE
];

IO_BOARD = [
    ["size", [38.12, 22.15, 10]],
    ["tolerance", 0.1],
    ["border", 3],
];
MCU_BOARD = [
    ["size", [33.34, 18.35, 10]],
    ["tolerance", 0.1],
    ["border", 3],
    ["port", [7.98, 2.92]]
];

TRRS = [
    ["size", [12.23, 6.06, 6.11]],
    ["port_dia", 5.53],
    ["tolerance", 0.1],
    ["border", 3],
];

IO_BOARD_POSITION = [
    middle(left(LITTLE), right(THUMB3)),
    min(bottom(INDEX), bottom(RING)) - get(IO_BOARD, "border") - get(IO_BOARD, "size").y / 2,
    0
];

IO_BOARD_BORDER_BOTTOM_RIGHT = [
    IO_BOARD_POSITION.x + get(IO_BOARD, "size").x / 2 + get(IO_BOARD, "border"),
    IO_BOARD_POSITION.y - get(IO_BOARD, "size").y / 2 - get(IO_BOARD, "border")
];

function mcu_board_housing() =
    let(
        board = get(MCU_BOARD, "size"),
        tolerance = get(MCU_BOARD, "tolerance"),
        border = get(MCU_BOARD, "border"),
        housing = grow(board, 2 * (tolerance + border))
    )
    [housing.x, housing.y, BASE_HEIGHT];
function mcu_board_housing_position() =
    let(
        housing_x = mcu_board_housing().x,
        x = left(INDEX) - housing_x,
        y = TRRS_OUTER_POSITION.y + TRRS_OUTER.y
    )
    [x, y, 0];
function mcu_board_housing_centre_xy() =
    let(
        position = mcu_board_housing_position(),
        size = mcu_board_housing()
    )
    [position.x + size.x / 2, position.y + size.y / 2, 0];
function mcu_board_cavity() =
    let(
        tolerance = get(MCU_BOARD, "tolerance"),
        size = grow(get(MCU_BOARD, "size"), 2 * tolerance)
    )
    [size.x, size.y, 10];



MCU_BOARD_CENTRE = [
    left(INDEX) - get(MCU_BOARD, "border") - get(MCU_BOARD, "size").x / 2,
    top(THUMB3) + get(MCU_BOARD, "border") + get(MCU_BOARD, "size").y / 2
];

MCU_BOARD_BORDER_TOP_LEFT = [
    MCU_BOARD_CENTRE.x - get(MCU_BOARD, "size").x / 2 - get(MCU_BOARD, "border"),
    MCU_BOARD_CENTRE.y + get(MCU_BOARD, "size").y / 2 + get(MCU_BOARD, "border")
];

MCU_BOARD_BORDER_BOTTOM_LEFT = [
    MCU_BOARD_BORDER_TOP_LEFT.x,
    MCU_BOARD_CENTRE.y - get(MCU_BOARD, "size").y / 2 - get(MCU_BOARD, "border")
];

TRRS_CAVITY = grow(get(TRRS, "size"), get(TRRS, "tolerance"));

TRRS_OUTER = grow(TRRS_CAVITY, get(TRRS, "border"));

TRRS_OUTER_POSITION = [left(THUMB1), top(THUMB1), 0];

CHANNEL_XSEC = [4, 2];

BASE = [
    ["height", 4.2],
    ["polygon", [
        bottom_left(THUMB1),
        bottom_right(THUMB1),
        diag_l2r(bottom_right(THUMB1), bottom(THUMB2)),
        bottom_right(THUMB2),
        diag_l2r(bottom_right(THUMB2), bottom(THUMB3)),
        bottom_right(THUMB3),
        diag_l2r(bottom_right(THUMB3), IO_BOARD_BORDER_BOTTOM_RIGHT.y),
        IO_BOARD_BORDER_BOTTOM_RIGHT,
        diag_l2r(IO_BOARD_BORDER_BOTTOM_RIGHT, bottom(LITTLE)),
        bottom_left(LITTLE),
        bottom_right(LITTLE),
        top_right(LITTLE),
        diag_r2l(top_right(RING), top(LITTLE)),
        top_right(RING),
        diag_r2l(top_right(MIDDLE), top(RING)),
        top_right(MIDDLE),
        top_left(MIDDLE),
        diag_l2r(top_left(MIDDLE), top(INDEX)),
        top_left(INDEX),
        diag_l2r(top_left(INDEX), TRRS_OUTER_POSITION.y + TRRS_OUTER.y),
        [TRRS_OUTER_POSITION.x, TRRS_OUTER_POSITION.y + TRRS_OUTER.y],
        top_left(THUMB1),
    ]]
];

function is_in(set, value) = set[0]==value ? true : false;
function tail(set) = len(set) >1 ? [for(i=[1:1:len(set)-1]) set[i]] : undef;
function head(set) = is_list(set) ? set[0] : undef;
function get(set, value) = set == undef ? undef : is_in(head(set), value) ? head(set)[1] : get(tail(set), value); 

function GridCoords(x, y, z) = [x*GRID_SIZE, y*GRID_SIZE, z*GRID_SIZE];    //Translate switch according to grid

function bottom(switch) =
    let(centre = get(switch, "position"))
    centre.y - GRID_SIZE / 2;
function top(switch) =
    let(centre = get(switch, "position"))
    centre.y + GRID_SIZE / 2;
function left(switch) =
    let(centre = get(switch, "position"))
    centre.x - GRID_SIZE / 2;
function right(switch) =
    let(centre = get(switch, "position"))
    centre.x + GRID_SIZE / 2;
function top_left(switch) = [left(switch), top(switch)];
function top_right(switch) = [right(switch), top(switch)];
function bottom_left(switch) = [left(switch), bottom(switch)];
function bottom_right(switch) = [right(switch), bottom(switch)];

function diag_l2r(start_position, y_to) =
    let(dist = y_to - start_position.y)
    [start_position.x + dist, y_to];

function diag_r2l(start_position, y_to) =
    let(dist = y_to - start_position.y)
    [start_position.x - dist, y_to];

function min(a, b) = a > b ? a : b;

function middle(first, second) =
    (first - second) / 2 + second;

function grow(size, modifier) =
    [size.x + modifier, size.y + modifier, size.z + modifier / 2];

function centre(position, size) =
    [position.x + size.x / 2, position.y + size.y / 2, position.z + size.z / 2];


module SocketColumn(position) {
    let(
        height = get(MX_SOCKET, "height")
    ){
        union(){
            translate([position.x, position.y, position.z + height/2]) 
                cube([GRID_SIZE, GRID_SIZE, height], center = true);

            translate([position.x, position.y, (position.z/2)]) 
                cube([GRID_SIZE, GRID_SIZE, position.z], center = true);
        } 
    }    
}

module MXCutout(position) {
    let(
        tolerance = get(MX_SOCKET, "tolerance"),
        height = get(MX_SOCKET, "height"),
        x = 13.9+tolerance,
        y = 13.8+tolerance,
        x2 = 5,
        y2 = 16        
    ){       
        translate([position.x, position.y, (position.z/2) + height/2]) 
            cube([x, y, position.z + height+0.1], center = true);        

        translate([position.x, position.y, (position.z/2) + height/2-1.4])
            cube([x2, y2, position.z + height], center = true);
    }
}

module IoCutout() {
    let(
        tolerance = get(IO_BOARD, "tolerance"),
        size = get(IO_BOARD, "size"),
        adjusted_size = [size.x + tolerance, size.y + tolerance, size.z]
    ){
        translate(IO_BOARD_POSITION)
            cube(size = adjusted_size, center = true);
    }
}

module McuCutout() {
    let(
        centre = mcu_board_housing_centre_xy()
    )
    translate([centre.x, centre.y, 0])
    cube(mcu_board_cavity(), center = true);
}

module McuPortCutout() {
    let(
        port = get(MCU_BOARD, "port"),
        x_offset = -mcu_board_housing().x / 2
    ){
        translate(MCU_BOARD_CENTRE)
        translate([x_offset, 0, 0])
        cube([40, port.x, port.y * 2], center = true);
    }
}

module TrrsPortCutout() {
    let(
        tolerance = get(TRRS, "tolerance"),
        length = get(TRRS, "size").x,
        radius = get(TRRS, "port_dia") / 2 + tolerance
    ){
        translate([left(THUMB1), centre(TRRS_OUTER_POSITION, TRRS_OUTER).y, TRRS_CAVITY.z / 2 - tolerance])
        rotate([0, 90, 0])
            cylinder(h = length, r = radius, center = true);
    }
}

module TrrsCavityCutout() {
    let(
        centre = centre(TRRS_OUTER_POSITION, TRRS_OUTER)
    ){
        translate([centre.x, centre.y, TRRS_CAVITY.z / 2 - get(TRRS, "tolerance")])
            cube(TRRS_CAVITY, center = true);
    }
}

module MakeSockets() {
        for (switch = SWITCH_PLACEMENT) {
            SocketColumn(get(switch, "position"));
        }
}

module MakeBaseplate() {
    linear_extrude(get(BASE, "height"))
        polygon(get(BASE, "polygon"));
}

module MakeCutouts() {
    for (switch = SWITCH_PLACEMENT) {
        MXCutout(get(switch, "position"));
    }
    IoCutout();
    if (SIDE == "right") {
        McuCutout();
        McuPortCutout();
    }
    TrrsPortCutout();
    TrrsCavityCutout();
    MakeChannels();
}


module MakeChannels() {
    translate(get(THUMB1, "position"))
    translate([0, 0, -0.1])
        cube([GRID_SIZE, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

    translate(get(THUMB1, "position"))
    translate([0, 0, -0.1])
    rotate([0, 0, 90])
    mirror([0, 1, 0])
        cube([GRID_SIZE / 1.5, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

    translate(get(THUMB2, "position"))
    translate([0,0, -0.1])
        cube([GRID_SIZE, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

    translate(get(THUMB3, "position"))
    translate([0,0, -0.1])
        cube([GRID_SIZE, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

    translate(get(INDEX, "position"))
    translate([0, 0, -0.1])
    rotate([0, 0, -90])
        cube([GRID_SIZE, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

    translate(get(MIDDLE, "position"))
    translate([0, 0, -0.1])
    rotate([0, 0, -90])
        cube([GRID_SIZE * 2, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);
    
    translate(get(RING, "position"))
    translate([0, 0, -0.1])
    rotate([0, 0, 90])
    mirror([1, 0, 0])
        cube([GRID_SIZE, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

    translate(get(LITTLE, "position"))
    translate([0, 0, -0.1])
    rotate([0, 0, 180])
        cube([GRID_SIZE * 2, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

    if (SIDE == "right") {
        translate(get(THUMB2, "position"))
        translate([0,0, -0.1])
        rotate([0, 0, 90])
            cube([GRID_SIZE, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);

        translate(MCU_BOARD_CENTRE)
        translate([0, -0.9, -0.1])
        mirror([0, 1, 0])
            cube([GRID_SIZE * 2, CHANNEL_XSEC.x, CHANNEL_XSEC.y]);
    }
}

module MakeTrrsOuter() {
    translate(TRRS_OUTER_POSITION)
        cube(TRRS_OUTER);
}

module MakeMcuHousing() {
    if (SIDE == "right") {
        translate(mcu_board_housing_position())
        cube(mcu_board_housing());
    }
}

MIRROR = SIDE == "right" ? 0 : 1;

mirror([MIRROR, 0, 0])
difference() {
    union() {
        MakeSockets();
        MakeMcuHousing();
        MakeBaseplate();
        MakeTrrsOuter();
        
    }
    MakeCutouts();
}
