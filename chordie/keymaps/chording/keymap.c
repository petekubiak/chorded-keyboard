#include QMK_KEYBOARD_H

#define H_kE ((HASH_TYPE) 1 << 0)
#define H_kT ((HASH_TYPE) 1 << 1)
#define H_kL ((HASH_TYPE) 1 << 2)
#define H_kD ((HASH_TYPE) 1 << 3)
#define H_LTB2 ((HASH_TYPE) 1 << 4)
#define H_LTB1 ((HASH_TYPE) 1 << 5)
#define H_LTB0 ((HASH_TYPE) 1 << 6)
#define H_RTB0 ((HASH_TYPE) 1 << 7)
#define H_RTB1 ((HASH_TYPE) 1 << 8)
#define H_RTB2 ((HASH_TYPE) 1 << 9)
#define H_kO ((HASH_TYPE) 1 << 10)
#define H_kS ((HASH_TYPE) 1 << 11)
#define H_kR ((HASH_TYPE) 1 << 12)
#define H_kA ((HASH_TYPE) 1 << 13)

enum internal_keycodes {
    kE = SAFE_RANGE,
    kT, kL, kD, LTB2, LTB1, LTB0, RTB0, RTB1, RTB2, kO, kS, kR, kA,
    FIRST_INTERNAL_KEYCODE = kE,
    LAST_INTERNAL_KEYCODE = kA
};

enum pseudolayers {
    ETLDOSRA, extra, ALWAYS_ON
};

#define CHORD_TIMEOUT 100
#define DANCE_TIMEOUT 200
#define LEADER_TIMEOUT 750
#define TAP_TIMEOUT 50
#define LONG_PRESS_MULTIPLIER 2
#define DYNAMIC_MACRO_MAX_LENGTH 20
#define COMMAND_MAX_LENGTH 5
#define STRING_MAX_LENGTH 16
#define LEADER_MAX_LENGTH 5
#define HASH_TYPE uint16_t
#define NUMBER_OF_KEYS 14
#define DEFAULT_PSEUDOLAYER ETLDOSRA

const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
    [0] = LAYOUT(kE, kT, kL, kD, LTB2, LTB1, LTB0, RTB0, RTB1, RTB2, kO, kS, kR, kA),
};
size_t keymapsCount = 1;

uint8_t keycodes_buffer_array[] = {
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};

uint8_t command_buffer[] = {
    0, 0, 0, 0, 0
};

uint16_t leader_buffer[] = {
    0, 0, 0, 0, 0
};

uint8_t dynamic_macro_buffer[] = {
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};

#include "pointing_device.h"

#include "keymap_uk.h"

enum chord_states {
    IDLE,
    READY,
    ACTIVATED,
    DEACTIVATED,
    PRESS_FROM_ACTIVE,
    FINISHED_FROM_ACTIVE,
    IDLE_IN_DANCE,
    READY_IN_DANCE,
    FINISHED,
    LOCKED,
    READY_LOCKED,
    RESTART,
    IN_ONE_SHOT
};

struct Chord {
    uint32_t keycodes_hash;
    uint8_t pseudolayer;
    uint8_t* state;
    uint8_t* counter;
    uint16_t value1;
    uint8_t value2;
    void (*function) (const struct Chord*);
};

uint8_t current_pseudolayer = DEFAULT_PSEUDOLAYER;
bool lock_next = false;
uint16_t chord_timer = 0;
uint16_t dance_timer = 0;
bool autoshift_mode = true;
uint8_t keycode_index = 0;
uint8_t command_mode = 0;
uint8_t command_ind = 0;
bool in_leader_mode = false;
uint8_t leader_ind = 0;
uint16_t leader_timer = 0;
uint8_t dynamic_macro_mode = false;
uint8_t dynamic_macro_ind = 0;
bool a_key_went_through = false;
struct Chord* last_chord = NULL;

bool handle_US_ANSI_shifted_keys(int16_t keycode, bool in) {
    bool is_US_ANSI_shifted = true;

    int16_t regular_keycode = KC_NO;
    switch (keycode) {
        case KC_TILDE:
            regular_keycode = KC_GRAVE;
            break;
        case KC_EXCLAIM:
            regular_keycode = KC_1;
            break;
        case KC_AT:
            regular_keycode = KC_2;
            break;
        case KC_HASH:
            regular_keycode = KC_3;
            break;
        case KC_DOLLAR:
            regular_keycode = KC_4;
            break;
        case KC_PERCENT:
            regular_keycode = KC_5;
            break;
        case KC_CIRCUMFLEX:
            regular_keycode = KC_6;
            break;
        case KC_AMPERSAND:
            regular_keycode = KC_7;
            break;
        case KC_ASTERISK:
            regular_keycode = KC_8;
            break;
        case KC_LEFT_PAREN:
            regular_keycode = KC_9;
            break;
        case KC_RIGHT_PAREN:
            regular_keycode = KC_0;
            break;
        case KC_UNDERSCORE:
            regular_keycode = KC_MINUS;
            break;
        case KC_PLUS:
            regular_keycode = KC_EQUAL;
            break;
        case KC_LEFT_CURLY_BRACE:
            regular_keycode = KC_LEFT_BRACKET;
            break;
        case KC_RIGHT_CURLY_BRACE:
            regular_keycode = KC_RIGHT_BRACKET;
            break;
        case KC_PIPE:
            regular_keycode = KC_BACKSLASH;
            break;
        case KC_COLON:
            regular_keycode = KC_SEMICOLON;
            break;
        case KC_DOUBLE_QUOTE:
            regular_keycode = KC_QUOTE;
            break;
        case KC_LEFT_ANGLE_BRACKET:
            regular_keycode = KC_COMMA;
            break;
        case KC_RIGHT_ANGLE_BRACKET:
            regular_keycode = KC_DOT;
            break;
        case KC_QUESTION:
            regular_keycode = KC_SLASH;
            break;
        default:
            is_US_ANSI_shifted = false;
    }
    if (is_US_ANSI_shifted) {
        if (in) {
            register_code(KC_LSFT);
            register_code(regular_keycode);
        } else {
            unregister_code(regular_keycode);
            unregister_code(KC_LSFT);
        }
    }
    return is_US_ANSI_shifted;
}

void key_in(int16_t keycode) {
    if (command_mode == 1 && command_ind < COMMAND_MAX_LENGTH) {
        command_buffer[command_ind] = keycode;
        command_ind++;
        a_key_went_through = true;
    } else if (in_leader_mode && leader_ind < LEADER_MAX_LENGTH) {
        leader_buffer[leader_ind] = keycode;
        leader_ind++;
        a_key_went_through = true;
    } else if (dynamic_macro_mode && dynamic_macro_ind < DYNAMIC_MACRO_MAX_LENGTH) {
        dynamic_macro_buffer[dynamic_macro_ind] = keycode;
        dynamic_macro_ind++;
        a_key_went_through = true;
    } else {
        if (!handle_US_ANSI_shifted_keys(keycode, true)) {
            register_code(keycode);
        }
        send_keyboard_report();
        a_key_went_through = true;
    }
}

void key_out(int16_t keycode) {
    if (command_mode == 0) {
        if (!handle_US_ANSI_shifted_keys(keycode, false)) {
            if (command_mode == 0 && in_leader_mode == false && dynamic_macro_mode == false) {
                unregister_code(keycode);
            }
        }
        send_keyboard_report();
    }
}

void tap_key(int16_t keycode) {
    key_in(keycode);
    wait_ms(TAP_TIMEOUT);
    key_out(keycode);
}

const char * const strings[] PROGMEM = {

};
void single_dance_mouse(const struct Chord* self) {
    report_mouse_t report = pointing_device_get_report();

    switch (*self->state) {
        case ACTIVATED:
            report.buttons |= self->value1;
            pointing_device_set_report(report);
            pointing_device_send();

            break;

        case DEACTIVATED:
            //report.buttons &= ~(self->value1);
            report.buttons = 0;
            pointing_device_set_report(report);
            pointing_device_send();
            *self->state = IDLE;
            break;
        case RESTART:
            //report.buttons &= ~(self->value1);
            report.buttons = 0;
            pointing_device_set_report(report);
            pointing_device_send();
            break;
        default:
            break;
    }
}

void single_dance(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            key_in(self->value1);
            break;
        case DEACTIVATED:
            key_out(self->value1);
            *self->state = IDLE;
            break;
        case RESTART:
            key_out(self->value1);
            break;
        default:
            break;
    }
}

void key_layer_dance(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            current_pseudolayer = self->value2;
            a_key_went_through = false;
            break;
        case DEACTIVATED:if (!a_key_went_through) {
                tap_key(self->value1);
            }
        case RESTART:
            if (!a_key_went_through) {
                //tap_key(self->value1);
            }
            current_pseudolayer = self->pseudolayer;
            *self->state = IDLE; // does not have effect if the state was RESTART
            break;
        default:
            break;
    }
}

void key_mod_dance(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            key_in(self->value2);
            a_key_went_through = false;
            break;
        case DEACTIVATED:
        case RESTART:
            key_out(self->value2);
            if (!a_key_went_through) {
                tap_key(self->value1);
            }
            *self->state = IDLE; // does not have effect if the state was RESTART
            break;
        default:
            break;
    }
}

void key_key_dance(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            break;
        case DEACTIVATED:
            tap_key(self->value1);
            *self->state = IDLE;
            break;
        case FINISHED:
        case PRESS_FROM_ACTIVE:
            key_in(self->value2);
            break;
        case RESTART:
            key_out(self->value2);
            break;
        default:
            break;
    }
}

void autoshift_dance_impl(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            *self->counter = 0;
            break;
        case DEACTIVATED:
        case RESTART:
            tap_key(self->value1);
            *self->state = IDLE;
            break;
        case FINISHED_FROM_ACTIVE:
            if (*self->counter == (LONG_PRESS_MULTIPLIER - 2)) {
                key_in(KC_LSFT);
                tap_key(self->value1);
                key_out(KC_LSFT);
                *self->state = IDLE;
                // the skip to IDLE is usually just a lag optimization,
                // in this case it has a logic function, on a short
                // press (still longer than a tap) the key does not get shifted
            } else {
                *self->counter += 1;
                *self->state = PRESS_FROM_ACTIVE;
                dance_timer = timer_read();
            }
            break;
        default:
            break;
    }
}

void autoshift_dance(const struct Chord* self) {
    if (autoshift_mode) {
        autoshift_dance_impl(self);
    } else {
        single_dance(self);
    }
}

void autoshift_toggle(const struct Chord* self){
    if (*self->state == ACTIVATED) {
        autoshift_mode = !autoshift_mode;
        *self->state = IDLE;
    }
}

void temp_pseudolayer(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            current_pseudolayer = self->value1;
            break;
        case DEACTIVATED:
            current_pseudolayer = self->pseudolayer;
            *self->state = IDLE;
            break;
        case RESTART:
            current_pseudolayer = self->pseudolayer;
            break;
        default:
            break;
    }
}

void temp_pseudolayer_alt(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            current_pseudolayer = self->value1;
            break;
        case DEACTIVATED:
            current_pseudolayer = self->value2;
            *self->state = IDLE;
            break;
        case RESTART:
            current_pseudolayer = self->value2;
            break;
        default:
            break;
    }
}

void perm_pseudolayer(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        current_pseudolayer = self->value1;
        *self->state = IDLE;
    }
}

void switch_layer(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        layer_move(self->value1);
        *self->state = IDLE;
    }
}

void lock(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        lock_next = true;
        *self->state = IDLE;
    }
}

void one_shot_key(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            break;
        case DEACTIVATED:
            key_in(self->value1);
            *self->state = IN_ONE_SHOT;
            break;
        case FINISHED:
        case PRESS_FROM_ACTIVE:
            key_in(self->value1);
            a_key_went_through = false;
            break;
        case RESTART:
            if (a_key_went_through) {
                key_out(self->value1);
            } else {
                *self->state = IN_ONE_SHOT;
            }
        default:
            break;
    }
}

void one_shot_layer(const struct Chord* self) {
    switch (*self->state) {
        case ACTIVATED:
            break;
        case DEACTIVATED:
            current_pseudolayer = self->value1;
            *self->state = IN_ONE_SHOT;
            break;
        case FINISHED:
        case PRESS_FROM_ACTIVE:
            current_pseudolayer = self->value1;
            a_key_went_through = false;
            break;
        case RESTART:
            if (a_key_went_through) {
                current_pseudolayer = self->pseudolayer;
            } else {
                *self->state = IN_ONE_SHOT;
            }
        default:
            break;
    }
}

void command(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        command_mode++;
        *self->state = IDLE;
    }
}

bool identical(uint16_t* buffer1, uint16_t* buffer2) {
    bool same = true;
    for (int i = 0; i < LEADER_MAX_LENGTH; i++) {
        same = same && (buffer1[i] == buffer2[i]);
    }
    return same;
}

void leader(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        in_leader_mode = true;
        *self->state = IDLE;
    }
}

void dynamic_macro_record(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        for (int i = 0; i < DYNAMIC_MACRO_MAX_LENGTH; i++) {
            dynamic_macro_buffer[i] = 0;
        }
        dynamic_macro_mode = true;
        *self->state = IDLE;
    }
}

void dynamic_macro_next(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        if (dynamic_macro_mode && dynamic_macro_ind < DYNAMIC_MACRO_MAX_LENGTH) {
            dynamic_macro_buffer[dynamic_macro_ind] = 0;
            dynamic_macro_ind++;
        }
        *self->state = IDLE;
    }
}

void dynamic_macro_end(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        if (dynamic_macro_mode) {
            dynamic_macro_mode = false;
        }
        *self->state = IDLE;
    }
}

void dynamic_macro_play(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        int ind_start = 0;
        while (ind_start < DYNAMIC_MACRO_MAX_LENGTH) {
            for (int i = ind_start; i < DYNAMIC_MACRO_MAX_LENGTH; i++) {
                if (dynamic_macro_buffer[i] == 0) {
                    break;
                }
                register_code(dynamic_macro_buffer[i]);
            }
            send_keyboard_report();
            wait_ms(TAP_TIMEOUT);
            for (int i = ind_start; i < DYNAMIC_MACRO_MAX_LENGTH; i++) {
                if (dynamic_macro_buffer[i] == 0) {
                    ind_start = i + 1;
                    break;
                }
                unregister_code(dynamic_macro_buffer[i]);
            }
            send_keyboard_report();
        }
        *self->state = IDLE;
    }
}

void string_in(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        char buffer[STRING_MAX_LENGTH];
        strcpy_P(buffer, (char*)pgm_read_word(&(strings[self->value1])));
        send_string(buffer);
    }
}

void clear(const struct Chord* self);

void reset_keyboard_kb(void){
#ifdef WATCHDOG_ENABLE
    MCUSR = 0;
    wdt_disable();
    wdt_reset();
#endif
    reset_keyboard();
}

void reset(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        reset_keyboard_kb();
    }
}

uint8_t state_0 = IDLE;
uint8_t counter_0 = 0;
const struct Chord chord_0 PROGMEM = {H_kE, ETLDOSRA, &state_0, &counter_0, KC_E, 0, autoshift_dance};
uint8_t state_1 = IDLE;
uint8_t counter_1 = 0;
const struct Chord chord_1 PROGMEM = {H_kT, ETLDOSRA, &state_1, &counter_1, KC_T, 0, autoshift_dance};
uint8_t state_2 = IDLE;
uint8_t counter_2 = 0;
const struct Chord chord_2 PROGMEM = {H_kL, ETLDOSRA, &state_2, &counter_2, KC_L, 0, autoshift_dance};
uint8_t state_3 = IDLE;
uint8_t counter_3 = 0;
const struct Chord chord_3 PROGMEM = {H_kD, ETLDOSRA, &state_3, &counter_3, KC_D, 0, autoshift_dance};
uint8_t state_4 = IDLE;
uint8_t counter_4 = 0;
const struct Chord chord_4 PROGMEM = {H_kO, ETLDOSRA, &state_4, &counter_4, KC_O, 0, autoshift_dance};
uint8_t state_5 = IDLE;
uint8_t counter_5 = 0;
const struct Chord chord_5 PROGMEM = {H_kS, ETLDOSRA, &state_5, &counter_5, KC_S, 0, autoshift_dance};
uint8_t state_6 = IDLE;
uint8_t counter_6 = 0;
const struct Chord chord_6 PROGMEM = {H_kR, ETLDOSRA, &state_6, &counter_6, KC_R, 0, autoshift_dance};
uint8_t state_7 = IDLE;
uint8_t counter_7 = 0;
const struct Chord chord_7 PROGMEM = {H_kA, ETLDOSRA, &state_7, &counter_7, KC_A, 0, autoshift_dance};
uint8_t state_8 = IDLE;
const struct Chord chord_8 PROGMEM = {H_LTB2, ETLDOSRA, &state_8, NULL, KC_RGUI, 0, single_dance};
uint8_t state_9 = IDLE;
const struct Chord chord_9 PROGMEM = {H_LTB1, ETLDOSRA, &state_9, NULL, KC_LSFT, 0, single_dance};
uint8_t state_10 = IDLE;
const struct Chord chord_10 PROGMEM = {H_LTB0, ETLDOSRA, &state_10, NULL, KC_ENT, 0, single_dance};
uint8_t state_11 = IDLE;
const struct Chord chord_11 PROGMEM = {H_RTB0, ETLDOSRA, &state_11, NULL, KC_LCTL, 0, single_dance};
uint8_t state_12 = IDLE;
const struct Chord chord_12 PROGMEM = {H_RTB1, ETLDOSRA, &state_12, NULL, KC_SPACE, 0, single_dance};
uint8_t state_13 = IDLE;
const struct Chord chord_13 PROGMEM = {H_RTB2, ETLDOSRA, &state_13, NULL, extra, 0, temp_pseudolayer};
uint8_t state_14 = IDLE;
const struct Chord chord_14 PROGMEM = {H_kE + H_kD + H_kO + H_kA, ETLDOSRA, &state_14, NULL, KC_CLEAR, 0, single_dance};
uint8_t state_15 = IDLE;
const struct Chord chord_15 PROGMEM = {H_kT + H_kL + H_kS + H_kR, ETLDOSRA, &state_15, NULL, KC_CAPS, 0, single_dance};
uint8_t state_16 = IDLE;
uint8_t counter_16 = 0;
const struct Chord chord_16 PROGMEM = {H_kE + H_kT, ETLDOSRA, &state_16, &counter_16, KC_Y, 0, autoshift_dance};
uint8_t state_17 = IDLE;
const struct Chord chord_17 PROGMEM = {H_kE + H_kL, ETLDOSRA, &state_17, NULL, KC_SLASH, 0, single_dance};
uint8_t state_18 = IDLE;
uint8_t counter_18 = 0;
const struct Chord chord_18 PROGMEM = {H_kE + H_kD, ETLDOSRA, &state_18, &counter_18, KC_2, 0, autoshift_dance};
uint8_t state_19 = IDLE;
uint8_t counter_19 = 0;
const struct Chord chord_19 PROGMEM = {H_kE + H_kO, ETLDOSRA, &state_19, &counter_19, KC_I, 0, autoshift_dance};
uint8_t state_20 = IDLE;
const struct Chord chord_20 PROGMEM = {H_kE + H_kS, ETLDOSRA, &state_20, NULL, UK_DQUO, 0, single_dance};
uint8_t state_21 = IDLE;
const struct Chord chord_21 PROGMEM = {H_kE + H_kR, ETLDOSRA, &state_21, NULL, KC_LEFT_BRACKET, 0, single_dance};
uint8_t state_22 = IDLE;
uint8_t counter_22 = 0;
const struct Chord chord_22 PROGMEM = {H_kE + H_kA, ETLDOSRA, &state_22, &counter_22, KC_U, 0, autoshift_dance};
uint8_t state_23 = IDLE;
const struct Chord chord_23 PROGMEM = {H_kT + H_kL, ETLDOSRA, &state_23, NULL, KC_RPRN, 0, single_dance};
uint8_t state_24 = IDLE;
uint8_t counter_24 = 0;
const struct Chord chord_24 PROGMEM = {H_kT + H_kD, ETLDOSRA, &state_24, &counter_24, KC_K, 0, autoshift_dance};
uint8_t state_25 = IDLE;
const struct Chord chord_25 PROGMEM = {H_kT + H_kO, ETLDOSRA, &state_25, NULL, KC_COLON, 0, single_dance};
uint8_t state_26 = IDLE;
uint8_t counter_26 = 0;
const struct Chord chord_26 PROGMEM = {H_kT + H_kS, ETLDOSRA, &state_26, &counter_26, KC_G, 0, autoshift_dance};
uint8_t state_27 = IDLE;
uint8_t counter_27 = 0;
const struct Chord chord_27 PROGMEM = {H_kT + H_kR, ETLDOSRA, &state_27, &counter_27, KC_M, 0, autoshift_dance};
uint8_t state_28 = IDLE;
uint8_t counter_28 = 0;
const struct Chord chord_28 PROGMEM = {H_kT + H_kA, ETLDOSRA, &state_28, &counter_28, KC_3, 0, autoshift_dance};
uint8_t state_29 = IDLE;
uint8_t counter_29 = 0;
const struct Chord chord_29 PROGMEM = {H_kL + H_kD, ETLDOSRA, &state_29, &counter_29, KC_W, 0, autoshift_dance};
uint8_t state_30 = IDLE;
uint8_t counter_30 = 0;
const struct Chord chord_30 PROGMEM = {H_kL + H_kO, ETLDOSRA, &state_30, &counter_30, KC_J, 0, autoshift_dance};
uint8_t state_31 = IDLE;
uint8_t counter_31 = 0;
const struct Chord chord_31 PROGMEM = {H_kL + H_kS, ETLDOSRA, &state_31, &counter_31, KC_C, 0, autoshift_dance};
uint8_t state_32 = IDLE;
uint8_t counter_32 = 0;
const struct Chord chord_32 PROGMEM = {H_kL + H_kR, ETLDOSRA, &state_32, &counter_32, KC_N, 0, autoshift_dance};
uint8_t state_33 = IDLE;
const struct Chord chord_33 PROGMEM = {H_kL + H_kA, ETLDOSRA, &state_33, NULL, KC_UNDERSCORE, 0, single_dance};
uint8_t state_34 = IDLE;
const struct Chord chord_34 PROGMEM = {H_kD + H_kO, ETLDOSRA, &state_34, NULL, KC_DOT, 0, single_dance};
uint8_t state_35 = IDLE;
uint8_t counter_35 = 0;
const struct Chord chord_35 PROGMEM = {H_kD + H_kS, ETLDOSRA, &state_35, &counter_35, KC_P, 0, autoshift_dance};
uint8_t state_36 = IDLE;
uint8_t counter_36 = 0;
const struct Chord chord_36 PROGMEM = {H_kD + H_kR, ETLDOSRA, &state_36, &counter_36, KC_H, 0, autoshift_dance};
uint8_t state_37 = IDLE;
uint8_t counter_37 = 0;
const struct Chord chord_37 PROGMEM = {H_kD + H_kA, ETLDOSRA, &state_37, &counter_37, KC_F, 0, autoshift_dance};
uint8_t state_38 = IDLE;
const struct Chord chord_38 PROGMEM = {H_kO + H_kS, ETLDOSRA, &state_38, NULL, KC_MINUS, 0, single_dance};
uint8_t state_39 = IDLE;
const struct Chord chord_39 PROGMEM = {H_kO + H_kR, ETLDOSRA, &state_39, NULL, KC_COMMA, 0, single_dance};
uint8_t state_40 = IDLE;
const struct Chord chord_40 PROGMEM = {H_kO + H_kA, ETLDOSRA, &state_40, NULL, KC_LPRN, 0, single_dance};
uint8_t state_41 = IDLE;
uint8_t counter_41 = 0;
const struct Chord chord_41 PROGMEM = {H_kS + H_kR, ETLDOSRA, &state_41, &counter_41, KC_B, 0, autoshift_dance};
uint8_t state_42 = IDLE;
uint8_t counter_42 = 0;
const struct Chord chord_42 PROGMEM = {H_kS + H_kA, ETLDOSRA, &state_42, &counter_42, KC_X, 0, autoshift_dance};
uint8_t state_43 = IDLE;
uint8_t counter_43 = 0;
const struct Chord chord_43 PROGMEM = {H_kR + H_kA, ETLDOSRA, &state_43, &counter_43, KC_1, 0, autoshift_dance};
uint8_t state_44 = IDLE;
uint8_t counter_44 = 0;
const struct Chord chord_44 PROGMEM = {H_kE + H_kT + H_kO, ETLDOSRA, &state_44, &counter_44, KC_4, 0, autoshift_dance};
uint8_t state_45 = IDLE;
const struct Chord chord_45 PROGMEM = {H_kE + H_kT + H_kS, ETLDOSRA, &state_45, NULL, UK_TILD, 0, single_dance};
uint8_t state_46 = IDLE;
const struct Chord chord_46 PROGMEM = {H_kE + H_kL + H_kO, ETLDOSRA, &state_46, NULL, UK_AT, 0, single_dance};
uint8_t state_47 = IDLE;
uint8_t counter_47 = 0;
const struct Chord chord_47 PROGMEM = {H_kE + H_kL + H_kS, ETLDOSRA, &state_47, &counter_47, KC_0, 0, autoshift_dance};
uint8_t state_48 = IDLE;
const struct Chord chord_48 PROGMEM = {H_kE + H_kD + H_kO, ETLDOSRA, &state_48, NULL, KC_EXCLAIM, 0, single_dance};
uint8_t state_49 = IDLE;
uint8_t counter_49 = 0;
const struct Chord chord_49 PROGMEM = {H_kE + H_kD + H_kS, ETLDOSRA, &state_49, &counter_49, KC_7, 0, autoshift_dance};
uint8_t state_50 = IDLE;
uint8_t counter_50 = 0;
const struct Chord chord_50 PROGMEM = {H_kE + H_kO + H_kS, ETLDOSRA, &state_50, &counter_50, KC_9, 0, autoshift_dance};
uint8_t state_51 = IDLE;
const struct Chord chord_51 PROGMEM = {H_kT + H_kL + H_kD, ETLDOSRA, &state_51, NULL, UK_PND, 0, single_dance};
uint8_t state_52 = IDLE;
const struct Chord chord_52 PROGMEM = {H_kT + H_kL + H_kO, ETLDOSRA, &state_52, NULL, KC_PERCENT, 0, single_dance};
uint8_t state_53 = IDLE;
const struct Chord chord_53 PROGMEM = {H_kT + H_kL + H_kS, ETLDOSRA, &state_53, NULL, UK_HASH, 0, single_dance};
uint8_t state_54 = IDLE;
const struct Chord chord_54 PROGMEM = {H_kT + H_kL + H_kR, ETLDOSRA, &state_54, NULL, KC_LEFT_CURLY_BRACE, 0, single_dance};
uint8_t state_55 = IDLE;
const struct Chord chord_55 PROGMEM = {H_kT + H_kD + H_kO, ETLDOSRA, &state_55, NULL, UK_BSLS, 0, single_dance};
uint8_t state_56 = IDLE;
uint8_t counter_56 = 0;
const struct Chord chord_56 PROGMEM = {H_kT + H_kD + H_kS, ETLDOSRA, &state_56, &counter_56, KC_V, 0, autoshift_dance};
uint8_t state_57 = IDLE;
uint8_t counter_57 = 0;
const struct Chord chord_57 PROGMEM = {H_kT + H_kD + H_kR, ETLDOSRA, &state_57, &counter_57, KC_8, 0, autoshift_dance};
uint8_t state_58 = IDLE;
const struct Chord chord_58 PROGMEM = {H_kT + H_kO + H_kS, ETLDOSRA, &state_58, NULL, UK_PIPE, 0, single_dance};
uint8_t state_59 = IDLE;
uint8_t counter_59 = 0;
const struct Chord chord_59 PROGMEM = {H_kT + H_kO + H_kR, ETLDOSRA, &state_59, &counter_59, KC_6, 0, autoshift_dance};
uint8_t state_60 = IDLE;
uint8_t counter_60 = 0;
const struct Chord chord_60 PROGMEM = {H_kT + H_kS + H_kR, ETLDOSRA, &state_60, &counter_60, KC_Z, 0, autoshift_dance};
uint8_t state_61 = IDLE;
const struct Chord chord_61 PROGMEM = {H_kL + H_kD + H_kO, ETLDOSRA, &state_61, NULL, KC_GRV, 0, single_dance};
uint8_t state_62 = IDLE;
const struct Chord chord_62 PROGMEM = {H_kL + H_kD + H_kS, ETLDOSRA, &state_62, NULL, KC_AMPERSAND, 0, single_dance};
uint8_t state_63 = IDLE;
const struct Chord chord_63 PROGMEM = {H_kL + H_kD + H_kR, ETLDOSRA, &state_63, NULL, KC_CIRCUMFLEX, 0, single_dance};
uint8_t state_64 = IDLE;
const struct Chord chord_64 PROGMEM = {H_kL + H_kD + H_kA, ETLDOSRA, &state_64, NULL, KC_QUOTE, 0, single_dance};
uint8_t state_65 = IDLE;
const struct Chord chord_65 PROGMEM = {H_kL + H_kO + H_kS, ETLDOSRA, &state_65, NULL, KC_EQUAL, 0, single_dance};
uint8_t state_66 = IDLE;
const struct Chord chord_66 PROGMEM = {H_kL + H_kO + H_kR, ETLDOSRA, &state_66, NULL, KC_DOLLAR, 0, single_dance};
uint8_t state_67 = IDLE;
uint8_t counter_67 = 0;
const struct Chord chord_67 PROGMEM = {H_kL + H_kS + H_kR, ETLDOSRA, &state_67, &counter_67, KC_5, 0, autoshift_dance};
uint8_t state_68 = IDLE;
const struct Chord chord_68 PROGMEM = {H_kL + H_kS + H_kA, ETLDOSRA, &state_68, NULL, KC_QUESTION, 0, single_dance};
uint8_t state_69 = IDLE;
const struct Chord chord_69 PROGMEM = {H_kD + H_kO + H_kS, ETLDOSRA, &state_69, NULL, KC_SEMICOLON, 0, single_dance};
uint8_t state_70 = IDLE;
const struct Chord chord_70 PROGMEM = {H_kD + H_kO + H_kR, ETLDOSRA, &state_70, NULL, KC_LEFT_ANGLE_BRACKET, 0, single_dance};
uint8_t state_71 = IDLE;
const struct Chord chord_71 PROGMEM = {H_kD + H_kO + H_kA, ETLDOSRA, &state_71, NULL, KC_RIGHT_CURLY_BRACE, 0, single_dance};
uint8_t state_72 = IDLE;
uint8_t counter_72 = 0;
const struct Chord chord_72 PROGMEM = {H_kD + H_kS + H_kR, ETLDOSRA, &state_72, &counter_72, KC_Q, 0, autoshift_dance};
uint8_t state_73 = IDLE;
const struct Chord chord_73 PROGMEM = {H_kD + H_kS + H_kA, ETLDOSRA, &state_73, NULL, KC_ASTERISK, 0, single_dance};
uint8_t state_74 = IDLE;
const struct Chord chord_74 PROGMEM = {H_kD + H_kR + H_kA, ETLDOSRA, &state_74, NULL, KC_RIGHT_ANGLE_BRACKET, 0, single_dance};
uint8_t state_75 = IDLE;
const struct Chord chord_75 PROGMEM = {H_kO + H_kS + H_kR, ETLDOSRA, &state_75, NULL, KC_RIGHT_BRACKET, 0, single_dance};
uint8_t state_76 = IDLE;
const struct Chord chord_76 PROGMEM = {H_kD, extra, &state_76, NULL, KC_ESC, 0, single_dance};
uint8_t state_77 = IDLE;
const struct Chord chord_77 PROGMEM = {H_kO, extra, &state_77, NULL, KC_BSPC, 0, single_dance};
uint8_t state_78 = IDLE;
const struct Chord chord_78 PROGMEM = {H_kS, extra, &state_78, NULL, KC_TAB, 0, single_dance};
uint8_t state_79 = IDLE;
const struct Chord chord_79 PROGMEM = {H_kT + H_kO, extra, &state_79, NULL, KC_LEFT, 0, single_dance};
uint8_t state_80 = IDLE;
const struct Chord chord_80 PROGMEM = {H_kL + H_kO, extra, &state_80, NULL, KC_DOWN, 0, single_dance};
uint8_t state_81 = IDLE;
const struct Chord chord_81 PROGMEM = {H_kT + H_kS, extra, &state_81, NULL, KC_UP, 0, single_dance};
uint8_t state_82 = IDLE;
const struct Chord chord_82 PROGMEM = {H_kO + H_kA, extra, &state_82, NULL, KC_RIGHT, 0, single_dance};

const struct Chord* const list_of_chords[] PROGMEM = {
    &chord_0, &chord_1, &chord_2, &chord_3, &chord_4, &chord_5, &chord_6, &chord_7, &chord_8, &chord_9, &chord_10, &chord_11, &chord_12, &chord_13, &chord_14, &chord_15, &chord_16, &chord_17, &chord_18, &chord_19, &chord_20, &chord_21, &chord_22, &chord_23, &chord_24, &chord_25, &chord_26, &chord_27, &chord_28, &chord_29, &chord_30, &chord_31, &chord_32, &chord_33, &chord_34, &chord_35, &chord_36, &chord_37, &chord_38, &chord_39, &chord_40, &chord_41, &chord_42, &chord_43, &chord_44, &chord_45, &chord_46, &chord_47, &chord_48, &chord_49, &chord_50, &chord_51, &chord_52, &chord_53, &chord_54, &chord_55, &chord_56, &chord_57, &chord_58, &chord_59, &chord_60, &chord_61, &chord_62, &chord_63, &chord_64, &chord_65, &chord_66, &chord_67, &chord_68, &chord_69, &chord_70, &chord_71, &chord_72, &chord_73, &chord_74, &chord_75, &chord_76, &chord_77, &chord_78, &chord_79, &chord_80, &chord_81, &chord_82
};

void ls_sshot(void) { SEND_STRING(SS_LSFT(SS_LCMD("s"))); }
void ls_winlock(void) { SEND_STRING(SS_LCMD("l")); }

const uint16_t leader_triggers[][LEADER_MAX_LENGTH] PROGMEM = {
    {KC_S, 0, 0, 0, 0},
    {KC_L, 0, 0, 0, 0},
};

void (*leader_functions[]) (void) = {
    &ls_sshot, &ls_winlock
};

#define NUMBER_OF_CHORDS 83
#define NUMBER_OF_LEADER_COMBOS 2

bool are_hashed_keycodes_in_sound(HASH_TYPE keycodes_hash, HASH_TYPE sound) {
    return (keycodes_hash & sound) == keycodes_hash;
}

uint8_t keycode_to_index(uint16_t keycode) {
    return keycode - FIRST_INTERNAL_KEYCODE;
}

void sound_keycode_array(uint16_t keycode) {
    uint8_t index = keycode_to_index(keycode);
    keycode_index++;
    keycodes_buffer_array[index] = keycode_index;
}

void silence_keycode_hash_array(HASH_TYPE keycode_hash) {
    for (int i = 0; i < NUMBER_OF_KEYS; i++) {
        bool index_in_hash = ((HASH_TYPE) 1 << i) & keycode_hash;
        if (index_in_hash) {
            uint8_t current_val = keycodes_buffer_array[i];
            keycodes_buffer_array[i] = 0;
            for (int j = 0; j < NUMBER_OF_KEYS; j++) {
                if (keycodes_buffer_array[j] > current_val) {
                    keycodes_buffer_array[j]--;
                }
            }
            keycode_index--;
        }
    }
}

bool are_hashed_keycodes_in_array(HASH_TYPE keycode_hash) {
    for (int i = 0; i < NUMBER_OF_KEYS; i++) {
        bool index_in_hash = ((HASH_TYPE) 1 << i) & keycode_hash;
        bool index_in_array = (bool) keycodes_buffer_array[i];
        if (index_in_hash && !index_in_array) {
            return false;
        }
    }
    return true;
}

void kill_one_shots(void) {
    struct Chord chord_storage;
    struct Chord* chord_ptr;
    struct Chord* chord;
    
    for (int i = 0; i < NUMBER_OF_CHORDS; i++) {
        chord_ptr = (struct Chord*) pgm_read_word (&list_of_chords[i]);
        memcpy_P(&chord_storage, chord_ptr, sizeof(struct Chord));
        chord = &chord_storage;
        
        if (*chord->state == IN_ONE_SHOT) {
            *chord->state = RESTART;
            chord->function(chord);
            if (*chord->state == RESTART) {
                *chord->state = IDLE;
            }
        }
    }
}

void process_finished_dances(void) {
    struct Chord chord_storage;
    struct Chord* chord_ptr;
    struct Chord* chord;
    
    for (int i = 0; i < NUMBER_OF_CHORDS; i++) {
        chord_ptr = (struct Chord*) pgm_read_word (&list_of_chords[i]);
        memcpy_P(&chord_storage, chord_ptr, sizeof(struct Chord));
        chord = &chord_storage;
        
        if (*chord->state == ACTIVATED) {
            *chord->state = PRESS_FROM_ACTIVE;
            chord->function(chord);
            if (a_key_went_through) {
                kill_one_shots();
            }
            dance_timer = timer_read();
        } else if (*chord->state == IDLE_IN_DANCE) {
            *chord->state = FINISHED;
            chord->function(chord);
            if (*chord->state == FINISHED) {
                *chord->state = RESTART;
                if (*chord->state == RESTART) {
                    *chord->state = IDLE;
                }
            }
        } else if (*chord->state == PRESS_FROM_ACTIVE) {
            *chord->state = FINISHED_FROM_ACTIVE;
            chord->function(chord);
            if (a_key_went_through) {
                kill_one_shots();
            }
            dance_timer = timer_read();
        }
    }
}

uint8_t keycodes_buffer_array_min(uint8_t* first_keycode_index) {
    for (int i = 0; i < NUMBER_OF_KEYS; i++) {
        if (keycodes_buffer_array[i] == 1) {
            if (first_keycode_index != NULL) {
                *first_keycode_index = (uint8_t) i;
            }
            return 1;
        }
    }
    return 0;
}

void remove_subchords(void) {
    struct Chord chord_storage;
    struct Chord* chord_ptr;
    struct Chord* chord;
    
    for (int i = 0; i < NUMBER_OF_CHORDS; i++) {
        chord_ptr = (struct Chord*) pgm_read_word (&list_of_chords[i]);
        memcpy_P(&chord_storage, chord_ptr, sizeof(struct Chord));
        chord = &chord_storage;
        
        if (!(*chord->state == READY || *chord->state == READY_IN_DANCE || *chord->state == READY_LOCKED)) {
            continue;
        }
        
        struct Chord chord_storage_2;
        struct Chord* chord_ptr_2;
        struct Chord* chord_2;
        for (int j = 0; j < NUMBER_OF_CHORDS; j++) {
            if (i == j) {continue;}
            
            chord_ptr_2 = (struct Chord*) pgm_read_word (&list_of_chords[j]);
            memcpy_P(&chord_storage_2, chord_ptr_2, sizeof(struct Chord));
            chord_2 = &chord_storage_2;
            
            if (are_hashed_keycodes_in_sound(chord_2->keycodes_hash, chord->keycodes_hash)) {
                if (*chord_2->state == READY) {
                    *chord_2->state = IDLE;
                }
                if (*chord_2->state == READY_IN_DANCE) {
                    *chord_2->state = IDLE_IN_DANCE;
                }
                if (*chord_2->state == READY_LOCKED) {
                    *chord_2->state = LOCKED;
                }
            }
        }
    }
}

void process_ready_chords(void) {
    uint8_t first_keycode_index = 0;
    while (keycodes_buffer_array_min(&first_keycode_index)) {
        // find ready chords
        struct Chord chord_storage;
        struct Chord* chord_ptr;
        struct Chord* chord;
        
        for (int i = 0; i < NUMBER_OF_CHORDS; i++) {
            chord_ptr = (struct Chord*) pgm_read_word (&list_of_chords[i]);
            memcpy_P(&chord_storage, chord_ptr, sizeof(struct Chord));
            chord = &chord_storage;
            
            // if the chord does not contain the first keycode
            bool contains_first_keycode = ((uint32_t) 1 << first_keycode_index) & chord->keycodes_hash;
            if (!contains_first_keycode) {
                continue;
            }
            
            if (!are_hashed_keycodes_in_array(chord->keycodes_hash)){
                continue;
            }
            
            if (*chord->state == LOCKED) {
                *chord->state = READY_LOCKED;
                continue;
            }
            
            if (!(chord->pseudolayer == current_pseudolayer || chord->pseudolayer == ALWAYS_ON)) {
                continue;
            }
            
            if (*chord->state == IDLE) {
                *chord->state = READY;
                continue;
            }
            
            if (*chord->state == IDLE_IN_DANCE) {
                *chord->state = READY_IN_DANCE;
            }
        }
        
        // remove subchords
        remove_subchords();
        
        // execute logic
        // this should be only one chord
        for (int i = 0; i < NUMBER_OF_CHORDS; i++) {
            chord_ptr = (struct Chord*) pgm_read_word (&list_of_chords[i]);
            memcpy_P(&chord_storage, chord_ptr, sizeof(struct Chord));
            chord = &chord_storage;
            
            if (*chord->state == READY_LOCKED) {
                *chord->state = RESTART;
                chord->function(chord);
                if (*chord->state == RESTART) {
                    *chord->state = IDLE;
                }
                break;
            }
            
            if (*chord->state == READY || *chord->state == READY_IN_DANCE) {
                if (last_chord && last_chord != chord) {
                    process_finished_dances();
                }
                
                bool lock_next_prev_state = lock_next;
                
                *chord->state = ACTIVATED;
                chord->function(chord);
                dance_timer = timer_read();
                
                if (lock_next && lock_next == lock_next_prev_state) {
                    lock_next = false;
                    *chord->state = PRESS_FROM_ACTIVE;
                    chord->function(chord);
                    if (*chord->state == PRESS_FROM_ACTIVE) {
                        *chord->state = LOCKED;
                    }
                    if (a_key_went_through) {
                        kill_one_shots();
                    }
                }
                break;
            }
        }
        
        // silence notes
        silence_keycode_hash_array(chord->keycodes_hash);
    }
}

void deactivate_active_chords(uint16_t keycode) {
    HASH_TYPE hash = (HASH_TYPE)1 << (keycode - SAFE_RANGE);
    bool broken;
    struct Chord chord_storage;
    struct Chord* chord_ptr;
    struct Chord* chord;
    
    for (int i = 0; i < NUMBER_OF_CHORDS; i++) {
        chord_ptr = (struct Chord*) pgm_read_word (&list_of_chords[i]);
        memcpy_P(&chord_storage, chord_ptr, sizeof(struct Chord));
        chord = &chord_storage;
        
        broken = are_hashed_keycodes_in_sound(hash, chord->keycodes_hash);
        if (!broken) {
            continue;
        }
        
        switch (*chord->state) {
            case ACTIVATED:
                *chord->state = DEACTIVATED;
                chord->function(chord);
                
                if (*chord->state == DEACTIVATED) {
                    dance_timer = timer_read();
                    *chord->state = IDLE_IN_DANCE;
                }
                if (*chord->state != IN_ONE_SHOT) {
                    kill_one_shots();
                }
                break;
            case PRESS_FROM_ACTIVE:
            case FINISHED_FROM_ACTIVE:
                *chord->state = RESTART;
                chord->function(chord);
                if (*chord->state == RESTART) {
                    *chord->state = IDLE;
                }
                kill_one_shots();
                break;
            default:
                break;
        }
    }
    
}

void process_command(void) {
    command_mode = 0;
    for (int i = 0; i < COMMAND_MAX_LENGTH; i++) {
        if (command_buffer[i]) {
            register_code(command_buffer[i]);
        }
        send_keyboard_report();
    }
    wait_ms(TAP_TIMEOUT);
    for (int i = 0; i < COMMAND_MAX_LENGTH; i++) {
        if (command_buffer[i]) {
            unregister_code(command_buffer[i]);
        }
        send_keyboard_report();
    }
    for (int i = 0; i < COMMAND_MAX_LENGTH; i++) {
        command_buffer[i] = 0;
    }
    command_ind = 0;
}

void process_leader(void) {
    in_leader_mode = false;
    for (int i = 0; i < NUMBER_OF_LEADER_COMBOS; i++) {
        uint16_t trigger[LEADER_MAX_LENGTH];
        memcpy_P(trigger, leader_triggers[i], LEADER_MAX_LENGTH * sizeof(uint16_t));
        
        if (identical(leader_buffer, trigger)) {
            (*leader_functions[i])();
            break;
        }
    }
    for (int i = 0; i < LEADER_MAX_LENGTH; i++) {
        leader_buffer[i] = 0;
    }
    leader_ind = 0;
}

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    if (keycode < FIRST_INTERNAL_KEYCODE || keycode > LAST_INTERNAL_KEYCODE) {        
        return true;
    }
    
    if (record->event.pressed) {
        sound_keycode_array(keycode);
    } else {
        process_ready_chords();
        deactivate_active_chords(keycode);
    }
    chord_timer = timer_read();
    leader_timer = timer_read();
    
    return false;
}

void matrix_scan_user(void) {
    bool chord_timer_expired = timer_elapsed(chord_timer) > CHORD_TIMEOUT;
    if (chord_timer_expired && keycodes_buffer_array_min(NULL)) {
        process_ready_chords();
    }
    
    bool dance_timer_expired = timer_elapsed(dance_timer) > DANCE_TIMEOUT;
    if (dance_timer_expired) { // would love to have && in_dance but not sure how
        process_finished_dances();
    }
    
    bool in_command_mode = command_mode == 2;
    if (in_command_mode) {
        process_command();
    }
    
    bool leader_timer_expired = timer_elapsed(leader_timer) > LEADER_TIMEOUT;
    if (leader_timer_expired && in_leader_mode) {
        process_leader();
    }
    
}

void clear(const struct Chord* self) {
    if (*self->state == ACTIVATED) {
        // kill all chords
        struct Chord chord_storage;
        struct Chord* chord_ptr;
        struct Chord* chord;
        
        for (int i = 0; i < NUMBER_OF_CHORDS; i++) {
            chord_ptr = (struct Chord*) pgm_read_word (&list_of_chords[i]);
            memcpy_P(&chord_storage, chord_ptr, sizeof(struct Chord));
            chord = &chord_storage;
            
            *chord->state = IDLE;
            
            if (chord->counter) {
                *chord->counter = 0;
            }
        }
        
        // clear keyboard
        clear_keyboard();
        send_keyboard_report();
        
        // switch to default pseudolayer
        current_pseudolayer = DEFAULT_PSEUDOLAYER;
        
        // clear all keyboard states
        lock_next = false;
        autoshift_mode = true;
        command_mode = 0;
        in_leader_mode = false;
        leader_ind = 0;
        dynamic_macro_mode = false;
        a_key_went_through = false;
        
        for (int i = 0; i < DYNAMIC_MACRO_MAX_LENGTH; i++) {
            dynamic_macro_buffer[i] = 0;
        }
    }
}