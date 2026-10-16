import { helper } from './helper';

export interface IUser {
    id: string;
    name: string;
}

export class UserService implements IUser {
    id: string;
    name: string;

    constructor(id: string, name: string) {
        this.id = id;
        this.name = name;
    }

    public async fetchDetails(): Promise<string> {
        helper();
        return this.name;
    }
}
