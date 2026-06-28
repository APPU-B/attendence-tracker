#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <unistd.h>

char csv_file_path[1024] = "attendance.csv";
char timetable_file_path[1024] = "timetable.csv";
#define CSV_FILE csv_file_path
#define TIMETABLE_FILE timetable_file_path
#define MAX_RECORDS 10000

typedef struct {
    char date[16];
    char subject[64];
    char status[16];
} AttendanceRecord;

typedef struct {
    char day[16];
    char subject[64];
} TimetableEntry;

typedef struct {
    char name[64];  /* This will store Subject (Day_of_Week) */
    int presents;
    int absents;
    int holidays;
    int total_active;
    double percentage;
    int below_threshold;
    int required_classes;
    int bunkable_classes;
} SubjectStats;

AttendanceRecord attendance[MAX_RECORDS];
int attendance_count = 0;

TimetableEntry timetable[1000];
int timetable_count = 0;

SubjectStats subjects[100];
int subject_count = 0;

// Helper to get today's date in dd-mm-yy
void get_today_date(char *date_str, size_t max_len) {
    time_t t = time(NULL);
    struct tm *tm_info = localtime(&t);
    strftime(date_str, max_len, "%d-%m-%y", tm_info);
}

// Helper to determine day of week for any dd-mm-yy string
int get_day_of_week(const char *date_str, char *out_day, size_t max_len) {
    int d, m, y;
    if (sscanf(date_str, "%d-%d-%d", &d, &m, &y) != 3) {
        return -1;
    }
    struct tm tm_info;
    memset(&tm_info, 0, sizeof(struct tm));
    tm_info.tm_mday = d;
    tm_info.tm_mon = m - 1;
    tm_info.tm_year = (y < 70) ? (y + 100) : y;
    tm_info.tm_isdst = -1;
    
    time_t t_val = mktime(&tm_info);
    if (t_val == -1) {
        return -1;
    }
    
    const char* days_of_week[] = {
        "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"
    };
    strncpy(out_day, days_of_week[tm_info.tm_wday], max_len - 1);
    out_day[max_len - 1] = '\0';
    return 0;
}

// Load attendance records
int load_attendance() {
    attendance_count = 0;
    FILE *fp = fopen(CSV_FILE, "r");
    if (!fp) {
        return 0;
    }
    char line[256];
    // Skip header line
    if (fgets(line, sizeof(line), fp) == NULL) {
        fclose(fp);
        return 0;
    }
    while (fgets(line, sizeof(line), fp) && attendance_count < MAX_RECORDS) {
        line[strcspn(line, "\r\n")] = '\0';
        if (strlen(line) == 0) continue;
        
        char *comma1 = strchr(line, ',');
        if (!comma1) continue;
        *comma1 = '\0';
        
        char *comma2 = strchr(comma1 + 1, ',');
        if (!comma2) continue;
        *comma2 = '\0';
        
        strncpy(attendance[attendance_count].date, line, sizeof(attendance[attendance_count].date) - 1);
        strncpy(attendance[attendance_count].subject, comma1 + 1, sizeof(attendance[attendance_count].subject) - 1);
        strncpy(attendance[attendance_count].status, comma2 + 1, sizeof(attendance[attendance_count].status) - 1);
        
        attendance[attendance_count].date[sizeof(attendance[attendance_count].date) - 1] = '\0';
        attendance[attendance_count].subject[sizeof(attendance[attendance_count].subject) - 1] = '\0';
        attendance[attendance_count].status[sizeof(attendance[attendance_count].status) - 1] = '\0';
        
        attendance_count++;
    }
    fclose(fp);
    return attendance_count;
}

// Save attendance records
void save_attendance() {
    FILE *fp = fopen(CSV_FILE, "w");
    if (!fp) {
        perror("Error opening attendance file");
        return;
    }
    fprintf(fp, "Date,Subject_Name,Status\n");
    for (int i = 0; i < attendance_count; i++) {
        fprintf(fp, "%s,%s,%s\n", attendance[i].date, attendance[i].subject, attendance[i].status);
    }
    fclose(fp);
}

// Load timetable
void load_timetable() {
    timetable_count = 0;
    FILE *fp = fopen(TIMETABLE_FILE, "r");
    if (!fp) return;
    char line[256];
    if (fgets(line, sizeof(line), fp) == NULL) {
        fclose(fp);
        return;
    }
    while (fgets(line, sizeof(line), fp) && timetable_count < 1000) {
        line[strcspn(line, "\r\n")] = '\0';
        if (strlen(line) == 0) continue;
        
        char *comma = strchr(line, ',');
        if (comma) {
            *comma = '\0';
            strncpy(timetable[timetable_count].day, line, sizeof(timetable[timetable_count].day) - 1);
            strncpy(timetable[timetable_count].subject, comma + 1, sizeof(timetable[timetable_count].subject) - 1);
            timetable[timetable_count].day[sizeof(timetable[timetable_count].day) - 1] = '\0';
            timetable[timetable_count].subject[sizeof(timetable[timetable_count].subject) - 1] = '\0';
            timetable_count++;
        }
    }
    fclose(fp);
}

// Check scheduled subjects for today, add Present by default if missing
void init_attendance() {
    load_attendance();
    load_timetable();
    
    char today[16];
    get_today_date(today, sizeof(today));
    
    char current_day[16];
    if (get_day_of_week(today, current_day, sizeof(current_day)) != 0) {
        printf("{\"status\": \"error\", \"message\": \"Failed to parse today's day of week\"}\n");
        return;
    }
    
    int added_count = 0;
    for (int i = 0; i < timetable_count; i++) {
        if (strcmp(timetable[i].day, current_day) == 0) {
            int found = 0;
            for (int j = 0; j < attendance_count; j++) {
                if (strcmp(attendance[j].date, today) == 0 && strcmp(attendance[j].subject, timetable[i].subject) == 0) {
                    found = 1;
                    break;
                }
            }
            if (!found && attendance_count < MAX_RECORDS) {
                strcpy(attendance[attendance_count].date, today);
                strcpy(attendance[attendance_count].subject, timetable[i].subject);
                strcpy(attendance[attendance_count].status, "Present");
                attendance_count++;
                added_count++;
            }
        }
    }
    
    if (added_count > 0) {
        save_attendance();
    }
    printf("{\"status\": \"initialized\", \"added_count\": %d, \"date\": \"%s\", \"day\": \"%s\"}\n", added_count, today, current_day);
}

// Update status of specific subject on specific date
void update_attendance_entry(const char *date, const char *subject, const char *status) {
    load_attendance();
    
    int found_index = -1;
    for (int i = 0; i < attendance_count; i++) {
        if (strcmp(attendance[i].date, date) == 0 && strcmp(attendance[i].subject, subject) == 0) {
            found_index = i;
            break;
        }
    }
    
    if (found_index != -1) {
        strncpy(attendance[found_index].status, status, sizeof(attendance[found_index].status) - 1);
        attendance[found_index].status[sizeof(attendance[found_index].status) - 1] = '\0';
    } else {
        if (attendance_count < MAX_RECORDS) {
            strncpy(attendance[attendance_count].date, date, sizeof(attendance[attendance_count].date) - 1);
            strncpy(attendance[attendance_count].subject, subject, sizeof(attendance[attendance_count].subject) - 1);
            strncpy(attendance[attendance_count].status, status, sizeof(attendance[attendance_count].status) - 1);
            
            attendance[attendance_count].date[sizeof(attendance[attendance_count].date) - 1] = '\0';
            attendance[attendance_count].subject[sizeof(attendance[attendance_count].subject) - 1] = '\0';
            attendance[attendance_count].status[sizeof(attendance[attendance_count].status) - 1] = '\0';
            
            attendance_count++;
        }
    }
    save_attendance();
    printf("{\"status\": \"updated\", \"date\": \"%s\", \"subject\": \"%s\", \"new_status\": \"%s\"}\n", date, subject, status);
}

// Calculate the predictive analytics metrics for each subject on each day independently
void calculate_analytics() {
    load_attendance();
    
    subject_count = 0;
    memset(subjects, 0, sizeof(subjects));
    
    for (int i = 0; i < attendance_count; i++) {
        const char *sub_name = attendance[i].subject;
        const char *status = attendance[i].status;
        
        int found_idx = -1;
        for (int j = 0; j < subject_count; j++) {
            if (strcmp(subjects[j].name, sub_name) == 0) {
                found_idx = j;
                break;
            }
        }
        
        if (found_idx == -1) {
            if (subject_count < 100) {
                found_idx = subject_count;
                strncpy(subjects[found_idx].name, sub_name, sizeof(subjects[found_idx].name) - 1);
                subjects[found_idx].name[sizeof(subjects[found_idx].name) - 1] = '\0';
                subject_count++;
            } else {
                continue;
            }
        }
        
        if (strcmp(status, "Present") == 0) {
            subjects[found_idx].presents++;
        } else if (strcmp(status, "Absent") == 0) {
            subjects[found_idx].absents++;
        } else if (strcmp(status, "Holiday") == 0) {
            subjects[found_idx].holidays++;
        }
    }
    
    // Add subjects from timetable that have no attendance records yet
    load_timetable();
    for (int i = 0; i < timetable_count; i++) {
        const char *sub_name = timetable[i].subject;
        int found_idx = -1;
        for (int j = 0; j < subject_count; j++) {
            if (strcmp(subjects[j].name, sub_name) == 0) {
                found_idx = j;
                break;
            }
        }
        if (found_idx == -1) {
            if (subject_count < 100) {
                strncpy(subjects[subject_count].name, sub_name, sizeof(subjects[subject_count].name) - 1);
                subjects[subject_count].name[sizeof(subjects[subject_count].name) - 1] = '\0';
                subjects[subject_count].presents = 0;
                subjects[subject_count].absents = 0;
                subjects[subject_count].holidays = 0;
                subjects[subject_count].total_active = 0;
                subjects[subject_count].percentage = 0.0;
                subjects[subject_count].below_threshold = 1;
                subjects[subject_count].required_classes = 1;
                subjects[subject_count].bunkable_classes = 0;
                subject_count++;
            }
        }
    }
    
    printf("[\n");
    for (int i = 0; i < subject_count; i++) {
        int P = subjects[i].presents;
        int A = subjects[i].absents;
        int H = subjects[i].holidays;
        int T = P + A;
        subjects[i].total_active = T;
        
        double pct = 100.0;
        int is_below = 0;
        int req_classes = 0;
        int bunk_classes = 0;
        
        if (T == 0) {
            pct = 0.0;
            is_below = 1;
            req_classes = 1;
            bunk_classes = 0;
        } else {
            pct = ((double)P / T) * 100.0;
            is_below = (pct < 82.0) ? 1 : 0;
            if (is_below) {
                double x_val = (0.82 * T - P) / 0.18;
                req_classes = (int)ceil(x_val);
                if (req_classes < 0) req_classes = 0;
            } else {
                double y_val = (P - 0.82 * T) / 0.82;
                bunk_classes = (int)floor(y_val);
                if (bunk_classes < 0) bunk_classes = 0;
            }
        }
        
        subjects[i].percentage = pct;
        subjects[i].below_threshold = is_below;
        subjects[i].required_classes = req_classes;
        subjects[i].bunkable_classes = bunk_classes;
        
        printf("  {\n");
        printf("    \"subject\": \"%s\",\n", subjects[i].name);
        printf("    \"presents\": %d,\n", P);
        printf("    \"absents\": %d,\n", A);
        printf("    \"holidays\": %d,\n", H);
        printf("    \"total_active\": %d,\n", T);
        printf("    \"percentage\": %.2f,\n", pct);
        printf("    \"below_threshold\": %s,\n", is_below ? "true" : "false");
        printf("    \"required_classes\": %d,\n", req_classes);
        printf("    \"bunkable_classes\": %d\n", bunk_classes);
        printf("  }%s\n", (i == subject_count - 1) ? "" : ",");
    }
    printf("]\n");
}

void resolve_paths() {
    const char *data_dir = getenv("DATA_DIR");
    if (data_dir && strlen(data_dir) > 0) {
        size_t len = strlen(data_dir);
        if (data_dir[len - 1] == '/') {
            snprintf(csv_file_path, sizeof(csv_file_path), "%sattendance.csv", data_dir);
            snprintf(timetable_file_path, sizeof(timetable_file_path), "%stimetable.csv", data_dir);
        } else {
            snprintf(csv_file_path, sizeof(csv_file_path), "%s/attendance.csv", data_dir);
            snprintf(timetable_file_path, sizeof(timetable_file_path), "%s/timetable.csv", data_dir);
        }
    } else if (access("/app/data/", F_OK) == 0) {
        snprintf(csv_file_path, sizeof(csv_file_path), "/app/data/attendance.csv");
        snprintf(timetable_file_path, sizeof(timetable_file_path), "/app/data/timetable.csv");
    } else {
        snprintf(csv_file_path, sizeof(csv_file_path), "attendance.csv");
        snprintf(timetable_file_path, sizeof(timetable_file_path), "timetable.csv");
    }
}

int main(int argc, char *argv[]) {
    resolve_paths();
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <init|update|status> [args...]\n", argv[0]);
        return 1;
    }
    
    if (strcmp(argv[1], "init") == 0) {
        init_attendance();
    } else if (strcmp(argv[1], "update") == 0) {
        if (argc < 5) {
            fprintf(stderr, "Usage: %s update <date> <subject> <status>\n", argv[0]);
            return 1;
        }
        if (strcmp(argv[4], "Present") != 0 && strcmp(argv[4], "Absent") != 0 && strcmp(argv[4], "Holiday") != 0) {
            fprintf(stderr, "Error: Invalid status '%s'. Must be Present, Absent, or Holiday.\n", argv[4]);
            return 1;
        }
        update_attendance_entry(argv[2], argv[3], argv[4]);
    } else if (strcmp(argv[1], "status") == 0) {
        calculate_analytics();
    } else {
        fprintf(stderr, "Error: Unknown command '%s'\n", argv[1]);
        return 1;
    }
    return 0;
}
