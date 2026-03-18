SOCKET_DIMENSION = 19.05;
SOCKET_HEIGHT = 8.2;

function socket_centre(position) =
	let(
		half_socket = SOCKET_DIMENSION / 2
	)
		[position.x + half_socket, position.y + half_socket, position.z];

function xy_centre(dimension) =
	[-dimension.x / 2, -dimension.y / 2, 0];

function grow(dimensions, factors) =
	[dimensions.x + factors.x, dimensions.y + factors.y, dimensions.z + factors.z];
	

module SocketOuter(position) {
		translate(position)
			cube([SOCKET_DIMENSION, SOCKET_DIMENSION, 8.2]);
}

module SocketCutout(position) {
	let (
		tolerance = 0.1,
		cutout_a_dimension = grow([13.9, 13.8, SOCKET_HEIGHT], [tolerance, tolerance, tolerance * 2]),
		cutout_b_dimension = grow([5, 16, SOCKET_HEIGHT - 1.4], [tolerance, tolerance, tolerance * 2])
	)
	union() {
		translate(socket_centre(position))
		translate([0, 0, -0.1])
		translate(xy_centre(cutout_a_dimension))
			cube(cutout_a_dimension);
		translate(socket_centre(position))
		translate([0, 0, -0.1])
		translate(xy_centre(cutout_b_dimension))
			cube(cutout_b_dimension);
	}
}

difference() {
	SocketOuter([0, 0, 0]);
	SocketCutout([0, 0, 0]);
}
